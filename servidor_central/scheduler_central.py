"""Scheduler del servidor central — sync SECOP cada 6 horas."""
import logging
from apscheduler.schedulers.blocking import BlockingScheduler

logger = logging.getLogger("scheduler_central")

def iniciar():
    from .ingestor_central import run_sync_completa
    sched = BlockingScheduler(timezone="America/Bogota")
    sched.add_job(run_sync_completa, "cron", hour="0,6,12,18", minute=0, id="sync_secop")
    logger.info("Scheduler central iniciado — sync cada 6h")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler detenido.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    iniciar()
