from os import path, environ, getcwd
from logging import handlers, Formatter, StreamHandler, DEBUG, INFO, getLogger
import yaml
from functools import cmp_to_key

import bs4 as bs
from requests import post, get
from requests.exceptions import ConnectionError

LOG_PATH = 'inu.log'

BASE_URL = "http://www.ipu.ac.in"
NOTICE_URL = BASE_URL + "/notices.php"
WORK_DIR = getcwd()
LAST_NOTICE = path.join(WORK_DIR, 'yaml', 'last.yaml')

TG_CHAT = "@test9971"
BOT_TOKEN = environ['bottoken']
T_API_RETRIES = 100


def setupLogging(logfile):
    logger = getLogger()
    logger.setLevel(DEBUG)

    # Set up logging to the logfile.
    filehandler = handlers.RotatingFileHandler(
        filename=logfile,
        maxBytes=5 * 1024 * 1024,
        backupCount=100)
    filehandler.setLevel(DEBUG)
    fileformatter = Formatter(
        '%(asctime)s %(levelname)-8s: %(message)s', datefmt='%m/%d/%Y %I:%M:%S %p')
    filehandler.setFormatter(fileformatter)
    logger.addHandler(filehandler)

    # Set up logging to the console.
    streamhandler = StreamHandler()
    streamhandler.setLevel(INFO)
    streamformatter = Formatter(
        '%(asctime)s [%(levelname)s]: %(message)s', datefmt='%I:%M:%S %p')
    streamhandler.setFormatter(streamformatter)
    logger.addHandler(streamhandler)

    return logger


def only_notice_tr(tag):
    return tag.name == 'tr' and not tag.has_attr('id')


def newer_date(date1, date2):
    """
    Return 0 if both dates are same otherwise
    If date1 > date2, return 1
    If date1 < date2, return -1
    """

    d1 = [int(s.lstrip('0')) for s in date1.split('-')]
    d2 = [int(s.lstrip('0')) for s in date2.split('-')]
    diff = (d1[0] - d2[0], d1[1] - d2[1], d1[2] - d2[2])

    def comp(a):
        if a > 0:
            return 1
        elif a < 0:
            return -1
        else:
            return 0

    date = comp(diff[2])
    if not date:
        date = comp(diff[1])
        if not date:
            date = comp(diff[0])
    return date


def load_last():
    if path.isfile(LAST_NOTICE):
        with open(LAST_NOTICE, 'r') as fr:
            l_notice = yaml.load(fr, Loader=yaml.CLoader)
            return l_notice
        logger.debug(f"Loaded last notice from {LAST_NOTICE}.")
    else:
        logger.debug(f"File {LAST_NOTICE} not found.")
        return None


def dump_last(notice):
    with open(LAST_NOTICE, 'w+') as fo:
        yaml.dump(notice, fo, Dumper=yaml.CDumper)
    logger.debug(f"Dumped '{notice['title'][:20]}' to {LAST_NOTICE}")


def _scrap_notice_tr(tr):
    tds = tr.find_all('td')
    # Check if only two tds are present
    if len(tds) != 2:
        return None

    # Gets the Notice name and download link
    notice_a = tds[0].a
    if notice_a:
        # Get the notice text and download url
        notice_txt = notice_a.text
        dwd_url = notice_a.get("href", None)
        if not dwd_url or not notice_txt:
            return None

        notice_date = tds[1].text
        if not notice_date:
            return None

        return {"date": notice_date.strip(), "title": " ".join(notice_txt.split()), "url": dwd_url.strip()}
    else:
        return None


def get_notices(soup):
    f_tr = soup.tbody.find(only_notice_tr)
    while f_tr:
        notice = _scrap_notice_tr(f_tr)

        f_tr = f_tr.nextSibling.nextSibling
        # def next_sib(t):
        #     if t and isinstance(t.nextSibling, bs.NavigableString):
        #         return next_sib(t.nextSibling)
        #     elif not t:
        #         return None
        #     else:
        #         return t.nextSibling
        # f_tr = next_sib(f_tr)

        if notice:
            yield notice


def send_msg(msg):
    telegram_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    params = (
        ('chat_id', TG_CHAT),
        ('text', msg),
        ('parse_mode', "Markdown"),
        ('disable_web_page_preview', "yes")
    )
    for _ in range(T_API_RETRIES):
        try:
            logger.debug(f"Sending message to /sendMessage.")

            logger.setLevel(INFO)
            telegram_req = post(telegram_url, params=params)
            logger.setLevel(DEBUG)

            if telegram_req.status_code == 200:
                logger.info("Sucessfully send to /sendDocument.")
                return True
            else:
                logger.error(
                    f"Recieved {telegram_req.status_code} http code from /sendDocument.")
                return False
        except ConnectionError:
            pass
    return False


def send_file(msg, fname, bfile):
    telegram_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    files = {'document': (fname, bfile)}
    data = (
        ('chat_id', TG_CHAT),
        ('caption', msg),
        ('parse_mode', "Markdown")
    )

    for _ in range(T_API_RETRIES):
        try:
            logger.debug(f"Sending file to /sendDocument.")

            logger.setLevel(INFO)
            telegram_req = post(telegram_url, data=data, files=files)
            logger.setLevel(DEBUG)

            if telegram_req.status_code == 200:
                logger.info("Sucessfully send to /sendDocument.")
                return True
            else:
                logger.error(
                    f"Recieved {telegram_req.status_code} http code from /sendDocument.")
                return False
        except ConnectionError:
            pass
    return False


def main():
    try:
        logger.debug(f"Retriving {NOTICE_URL}.")

        html = get(NOTICE_URL).text
        soup = bs.BeautifulSoup(html, 'lxml')

        n_gen = get_notices(soup)

        last_notice = load_last()

        # Get the New Notices
        notices = []
        for nt in n_gen:
            if nt != last_notice:
                logger.info(f"Found New Notice - {nt}")
                notices.append(nt)
            else:
                break

        notices.sort(key=cmp_to_key(
            lambda x, y: newer_date(x['date'], y['date'])))

        for n in notices:
            logger.info(f"Sending {n}.")
            try:
                logger.info(f"Downloading notice file {n['url']} .")
                n_content = get(BASE_URL + n['url']).content
            except:
                logger.error("Failed to download file.")
                msg = f"{n['title']} \n    - [Download]({n['url']}) \n**Date:-** {n['date']}"
                res1 = send_msg(msg)
            else:
                logger.info(f"Download complete for {n['url']} .")
                # msg = f"{n['title']} \n\nDate:- {n['date']}"
                msg = f"Date:- {n['date']} \n{n['title']}"
                res1 = send_file(msg, path.basename(n['url']), n_content)

            finally:
                if res1:
                    dump_last(n)
                else:
                    logger.critical(
                        f"Failed to send {n} after {T_API_RETRIES} retries.")

    except Exception as ex:
        logger.fatal(str(ex))
        raise ex


if __name__ == "__main__":
    logger = setupLogging(LOG_PATH)

    logger.info("SCRIPT STARTED")
    main()
    logger.info("SCRIPT ENDED")
