#!/usr/bin/env python3
""" GGSIPU Tracker Script """

from os import path, environ, getcwd, system, makedirs
from logging import handlers, Formatter, StreamHandler, DEBUG, INFO, getLogger
from functools import cmp_to_key
from datetime import datetime


import yaml
import bs4 as bs
from requests import post, get
from requests.exceptions import ConnectionError

LOG_PATH = 'inu.log'
UPLOAD_EXT = ('pdf', 'jpg', 'jpeg', 'png', 'ppt', 'pptx',
              'doc', 'docx', 'xls', 'xlsx', 'csv', 'zip', 'rar')


TG_CHAT = environ.get("TG_CHAT", "@ggsipu_notices")
BOT_TOKEN = environ['BOT_TOKEN']
GIT_OAUTH_TOKEN = environ['GIT_OAUTH_TOKEN']
GIT_REPO = environ['GIT_REPO']
GIT_BRANCH = environ.get('GIT_BRANCH', 'notice-archive')

BASE_URL = "http://www.ipu.ac.in"
NOTICE_URL = BASE_URL + "/notices.php"
WORK_DIR = getcwd()
LAST_NOTICE = path.join(WORK_DIR, 'yaml', 'last.yml')
LAST_NOTICE_REMOTE = f"https://raw.githubusercontent.com/{GIT_REPO}/{GIT_BRANCH}/yaml/last.yml"


T_API_RETRIES = 100

PRODUCTION = environ.get('PRODUCTION', None)


def setupLogging(logfile, to_file=True):
    logger = getLogger()
    logger.setLevel(DEBUG)

    if to_file:
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
    streamhandler.setLevel(DEBUG)
    streamformatter = Formatter(
        '[%(levelname)s]: %(message)s')
    streamhandler.setFormatter(streamformatter)
    logger.addHandler(streamhandler)

    return logger


def git_commit_push():
    """
    git add - git commit - git push
    [source -https://github.com/XiaomiFirmwareUpdater/mi-firmware-updater/blob/master/xfu.py]
    """
    now = str(datetime.today()).split('.')[0]
    system("git add {2} && "" \
           ""git -c \"user.name=GGSIPUTracker\" "
           "-c \"user.email=ggsipuresulttracker@@gmail.com\" "
           "commit -m \"sync: {0}\" && "" \
           ""git push -f -q https://{1}@github.com/{3}.git HEAD:{4}"
           .format(now, GIT_OAUTH_TOKEN, LAST_NOTICE, GIT_REPO, GIT_BRANCH))


def only_new_notice_tr(tag):
    return tag.name == 'tr' and not tag.has_attr('id') and not tag.has_attr('style')


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
    l_notice = None
    logger.debug("Loading Last sent notice.")
    if PRODUCTION:
        logger.debug(f"Retriving {LAST_NOTICE_REMOTE}.")

        l_yml = get(LAST_NOTICE_REMOTE).text
        l_notice = yaml.load(l_yml, Loader=yaml.CLoader)
    else:
        if path.isfile(LAST_NOTICE):
            with open(LAST_NOTICE, 'r') as fr:
                l_notice = yaml.load(fr, Loader=yaml.CLoader)

            logger.debug(f"Found file {LAST_NOTICE}.")
        else:
            logger.debug(f"file {LAST_NOTICE} not found.")
    return l_notice


def dump_last(notice):
    with open(LAST_NOTICE, 'w+') as fo:
        yaml.dump(notice, fo, Dumper=yaml.CDumper)
    logger.debug(f"Dumped '{notice}' to {LAST_NOTICE}")


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

        # Remove newlines, extra whitespaces and
        # escape Special Markdown Characters.

        # title = " ".join(''.join([c for c in w if c not in (
        #     '`', '_', '*', '\n', '\t')]) for w in notice_txt.split())
        title = " ".join(notice_txt.split())
        title = title.translate(str.maketrans({"_":  r"\_",
                                               "*":  r"\*",
                                               "`":  r"\`"}))

        return {"date": notice_date.strip(), "title": title, "url": dwd_url.strip()}
    else:
        return None


def get_notices(soup):
    f_trs = soup.tbody.find_all(only_new_notice_tr)
    for f_tr in f_trs:
        notice = _scrap_notice_tr(f_tr)

        # f_tr = f_tr.nextSibling.nextSibling
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


def tel_send_msg(msg):
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
                logger.debug("Sucessfully send to /sendDocument.")
                return True
            else:
                logger.debug(
                    f"Failed to send message. Recieved {telegram_req.status_code} http code from /sendDocument.")
                return False
        except ConnectionError:
            pass
    logger.critical(
        f"Failed to send message after {T_API_RETRIES} retries.")
    return False


def tel_send_file(msg, fname, bfile):
    telegram_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    files = {'document': (fname, bfile)}
    data = (
        ('chat_id', TG_CHAT),
        ('caption', msg),
        ('parse_mode', "Markdown")
    )

    for _ in range(T_API_RETRIES):
        try:
            logger.debug(f"Sending file [{fname}] to /sendDocument.")

            logger.setLevel(INFO)
            telegram_req = post(telegram_url, data=data, files=files)
            logger.setLevel(DEBUG)

            if telegram_req.status_code == 200:
                logger.debug(f"Sucessfully send [{fname}] to /sendDocument.")
                return True
            else:
                logger.debug(
                    f"Failed to send [{fname}]. Recieved {telegram_req.status_code} http code from /sendDocument.")
                return False
        except ConnectionError:
            pass
    logger.critical(
        f"Failed to send [{fname}] after {T_API_RETRIES} retries.")
    return False


def tel_send(notice):
    msg_file = f"Date :- {notice['date']} \n{notice['title']}"
    msg_no_file = f"*Date :- * {notice['date']} \n{notice['title']} \n   → [Open]({BASE_URL + notice['url']})"

    res = False
    if path.basename(notice['url']).split('.')[-1].lower() in UPLOAD_EXT:
        try:
            logger.debug(f"Downloading file {notice['url']}")
            n_content = get(BASE_URL + notice['url']).content
        except:
            logger.error(f"Download Failed for {notice['url']}")
            res = tel_send_msg(msg_no_file)
        else:
            logger.debug(f"Downloading Complete for file {notice['url']}")
            res = tel_send_file(
                msg_file, path.basename(notice['url']), n_content)
            # If /sendDocument fail due to 413(Large File), etc then
            # try sendMessage as fallback
            if not res:
                logger.debug('Fallback to /sendMessage.')
                res = tel_send_msg(msg_no_file)
    else:
        res = tel_send_msg(msg_no_file)

    return res


def main():
    try:
        logger.info(f"Retriving {NOTICE_URL}.")

        html = get(NOTICE_URL).text
        soup = bs.BeautifulSoup(html, 'lxml')

        n_gen = get_notices(soup)

        last_notice = load_last()
        if last_notice:
            logger.info(f"Loaded last notice - {last_notice}")
        else:
            logger.info(
                f"No last notice. SCRIPT RUNNING FOR FIRST TIME in current enviornment.")

        # Get the New Notices
        notices = []
        for nt in n_gen:
            if nt != last_notice:
                logger.info(f"Found New Notice - {nt}")
                notices.append(nt)
            else:
                break

        logger.info(f"{len(notices)} New Notices found !")

        if len(notices) == 0:
            return

        for n in reversed(notices):
            logger.info(f"SENDING {n}.")
            result = tel_send(n)
            if result:
                logger.info(f"SUCESSFULLY SENT {n}.")
                dump_last(n)
            else:
                logger.error(f"FAILED to SENT {n}.")

        if PRODUCTION:
            logger.info("Pushing changes to git repo.")
            git_commit_push()

    except Exception as ex:
        logger.exception(str(ex))


if __name__ == "__main__":

    if PRODUCTION:
        logger = setupLogging(LOG_PATH, False)
        logger.info("SCRIPT STARTED [ON SERVER]")
    else:
        logger = setupLogging(LOG_PATH, True)
        logger.info("SCRIPT STARTED [LOCAL]")

    # Create yaml directory if not exist
    if not path.isdir('yaml'):
        logger.warning("No yaml folder found. Creating yaml folder.")
        makedirs('yaml')

    main()
    logger.info("SCRIPT ENDED")
