import logging
import os
from queue import Queue
from random import shuffle
from threading import Thread
from typing import List

import click
import numpy as np
from pushover import Client
from xvfbwrapper import Xvfb
from datetime import datetime

from auditor import settings
from auditor.ad_writer import AdWriter
from auditor.agent import Agent
from auditor.scrapers.advertisement.chicago_reader import ChicagoReaderScraper
from auditor.scrapers.advertisement.chicago_tribune import ChicagoTribuneScraper
from auditor.scrapers.advertisement.cnn import CNNAdScraper
from auditor.scrapers.advertisement.fox_champaign import FoxChampaignScraper
from auditor.scrapers.advertisement.google_search import GoogleSearchAdScraper
from auditor.scrapers.advertisement.homefinder import HomeFinderAdScraper
from auditor.scrapers.advertisement.news_gazette_scraper import NewsGazetteAdScraper
from auditor.scrapers.advertisement.suntimes import SunTimesAdScraper
from auditor.scrapers.advertisement.wcia import WCIAScraper
from auditor.scrapers.ranking.realtor_ranking import RealtorRanking
from auditor.scrapers.ranking.redfin_ranking import RedfinScraper
from auditor.scrapers.ranking.trulia_ranking import TruliaScraper
from auditor.scrapers.ranking.zillow_ranking import ZillowScraper


def pos_int_norm(center: int, stddev: int):
    return abs(int(np.random.normal(center, stddev)))


def generate_qc_agents(proxy_config=None):
    from auditor.treatments.qc.gender import apply_male_treatment
    from auditor.treatments.qc.gender import apply_female_treatment
    from auditor.treatments.qc.ethnicity import apply_caucasian_treatment
    from auditor.treatments.qc.ethnicity import apply_afam_treatment
    from auditor.treatments.qc.ethnicity import apply_hispanic_treatment
    from auditor.treatments.qc.ethnicity import apply_asian_treatment
    return [
        apply_caucasian_treatment(apply_male_treatment(Agent("caucasian-male", proxy=proxy_config))),
        apply_caucasian_treatment(apply_female_treatment(Agent("caucasian-female", proxy=proxy_config))),
        apply_afam_treatment(apply_male_treatment(Agent("afam-male", proxy=proxy_config))),
        apply_afam_treatment(apply_female_treatment(Agent("afam-female", proxy=proxy_config))),
        apply_hispanic_treatment(apply_male_treatment(Agent("hispanic-male", proxy=proxy_config))),
        apply_hispanic_treatment(apply_female_treatment(Agent("hispanic-female", proxy=proxy_config))),
        apply_asian_treatment(apply_male_treatment(Agent("asian-male", proxy=proxy_config))),
        apply_asian_treatment(apply_female_treatment(Agent("asian-female", proxy=proxy_config))),
    ]


def generate_test_agent(proxy_config=None):
    from auditor.treatments.single_site import apply_control_treatment
    return [apply_control_treatment(Agent("test", proxy=proxy_config))]


def generate_single_site_agents(proxy_config=None):
    from auditor.treatments.single_site import apply_caucasian_treatment
    from auditor.treatments.single_site import apply_male_treatment
    from auditor.treatments.single_site import apply_female_treatment
    from auditor.treatments.single_site import apply_afam_treatment
    from auditor.treatments.single_site import apply_hispanic_treatment
    from auditor.treatments.single_site import apply_asian_treatment
    from auditor.treatments.single_site import apply_control_treatment
    return [
        apply_control_treatment(Agent("control", proxy=proxy_config)),
        apply_caucasian_treatment(
            apply_male_treatment(apply_control_treatment(Agent("caucasian-male", proxy=proxy_config)))),
        apply_caucasian_treatment(
            apply_female_treatment(apply_control_treatment(Agent("caucasian-female", proxy=proxy_config)))),
        apply_afam_treatment(apply_male_treatment(apply_control_treatment(Agent("afam-male", proxy=proxy_config)))),
        apply_afam_treatment(apply_female_treatment(apply_control_treatment(Agent("afam-female", proxy=proxy_config)))),
        apply_hispanic_treatment(
            apply_male_treatment(apply_control_treatment(Agent("hispanic-male", proxy=proxy_config)))),
        apply_hispanic_treatment(
            apply_female_treatment(apply_control_treatment(Agent("hispanic-female", proxy=proxy_config)))),
        apply_asian_treatment(apply_male_treatment(apply_control_treatment(Agent("asian-male", proxy=proxy_config)))),
        apply_asian_treatment(
            apply_female_treatment(apply_control_treatment(Agent("asian-female", proxy=proxy_config)))),
    ]


@click.command()
@click.option('-o', '--output', help='File to send output to', type=click.Path(exists=False))
@click.option('-a', '--agents', help='The number of agents per treatment', type=click.INT, default=1)
@click.option('-b', '--blocks', help='The number of blocks to run', type=click.INT, default=1)
@click.option('--location', type=click.Choice(['champaign', 'chicago', 'sacramento', 'atlanta']), default='champaign')
@click.option('-v', '--debug', is_flag=True)
def main(output, agents, blocks, location, debug):
    os.makedirs("output/failures", exist_ok=True)

    if debug:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    logging.basicConfig(
        level=log_level,
        handlers=[
            logging.FileHandler(f"output/{datetime.now()}.log"),
            logging.StreamHandler(),
        ]
    )
    logging.getLogger("selenium.webdriver").setLevel(logging.WARNING)
    logger = logging.getLogger(__name__)
    pushover_client = Client(settings.PUSHOVER_USERKEY, api_token=settings.PUSHOVER_TOKEN)

    treatments: List[Agent] = list()
    with Xvfb(width=1280, height=740) as xvfb:
        try:
            for block in range(blocks):
                logger.info("Starting block %s", block)
                logger.info("Creating agents")

                try:
                    for _num in range(agents):
                        from auditor.settings import proxy_config
                        treatments.extend(generate_qc_agents(proxy_config=settings.proxy_config))
                        # treatments.extend(generate_single_site_agents(proxy_config=proxy_config))
                        # treatments.extend(generate_test_agent(proxy_config=proxy_config))

                    logger.info("Adding scrape steps")
                    for treatment in treatments:
                        scrape_steps = {
                            'champaign': [
                                CNNAdScraper(delay=pos_int_norm(40, 12)),
                                CNNAdScraper(delay=pos_int_norm(40, 12)),
                                NewsGazetteAdScraper(),
                                NewsGazetteAdScraper(),
                                FoxChampaignScraper(),
                                FoxChampaignScraper(),
                                WCIAScraper(),
                                WCIAScraper(),
                                GoogleSearchAdScraper('houses in champaign', delay=pos_int_norm(40, 12)),
                                HomeFinderAdScraper('Urbana, IL', delay=pos_int_norm(40, 12)),
                                TruliaScraper('Champaign, IL', delay=pos_int_norm(600, 120)),
                                RealtorRanking('Champaign, IL', delay=10),
                                # RedfinScraper('county/721/IL/Champaign-County', delay=300),
                            ],
                            'chicago': [
                                CNNAdScraper(),
                                CNNAdScraper(),
                                ChicagoReaderScraper(delay=pos_int_norm(40, 12)),
                                ChicagoReaderScraper(delay=pos_int_norm(40, 12)),
                                SunTimesAdScraper(),
                                SunTimesAdScraper(),
                                ChicagoTribuneScraper(),
                                ChicagoTribuneScraper(),
                                GoogleSearchAdScraper('houses in chicago', delay=pos_int_norm(40, 12)),
                                HomeFinderAdScraper('Chicago, IL', delay=pos_int_norm(40, 12)),
                                RealtorRanking('Chicago, IL', delay=300),
                                TruliaScraper('Chicago, IL', delay=pos_int_norm(600, 120)),
                                # RedfinScraper('city/29470/IL/Chicago', delay=300),
                            ],
                            'atlanta': [
                                RealtorRanking('Atlanta, GA', delay=300),
                                TruliaScraper('Atlanta, GA', delay=pos_int_norm(600, 120)),
                            ],
                            'sacramento': [
                                RealtorRanking('Sacramento, CA', delay=300),
                                TruliaScraper('Sacramento, CA', delay=pos_int_norm(600, 120)),
                            ],
                        }

                        treatment.scrape_steps.extend(scrape_steps[location])

                    for agent in treatments:
                        shuffle(agent.training_steps)
                        shuffle(agent.scrape_steps)

                    queue = Queue()
                    writer = AdWriter(output, queue)

                    logger.info("Starting threads")
                    threads = [Thread(target=unit.run, args=(writer.queue,)) for unit in treatments]
                    for t in threads:
                        t.start()
                    writer.start()
                    for t in threads:
                        t.join()
                    writer.queue.put(None)
                    writer.join()
                except Exception as ex:
                    pushover_client.send_message("Error encountered in experiment")
                finally:
                    for treatment in treatments:
                        treatment.driver.quit()
                    logger.info("Completed block %s", block)
            pushover_client.send_message("Successfully finished an experiment")
            logger.info("Completed measurement")
        except (Exception, KeyboardInterrupt):
            try:
                for treatment in treatments:
                    treatment.quit()
            except:
                logger.exception("Exception quitting")


if __name__ == '__main__':
    main()
