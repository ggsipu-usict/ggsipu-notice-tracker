from os import path, environ, getcwd
import logging
import yaml

import bs4 as bs
from requests import post, get
from requests.exceptions import ConnectionError


BASE_URL = "http://www.ipu.ac.in"
NOTICE_URL = BASE_URL + "/notices.php"
WORK_DIR = getcwd()
LAST_NOTICE = path.join(WORK_DIR, 'yaml', 'last.yaml')

TG_CHAT = "@test9971"
BOT_TOKEN = environ['bottoken']
T_API_RETRIES = 100


logging.basicConfig(filename='inu.log', filemode='a+', level=logging.DEBUG,
                    format='%(asctime)s [%(levelname)s]: %(message)s',
                    datefmt='%m/%d/%Y %I:%M:%S %p')


def only_notice_tr(tag):
    return tag.name == 'tr' and not tag.has_attr('id')


def newer_date(date1, date2):
    """
    Return None if both dates are same otherwise
    newer date
    """

    d1 = [int(s.lstrip('0')) for s in date1.split('-')]
    d2 = [int(s.lstrip('0')) for s in date2.split('-')]
    diff = (d1[0] - d2[0], d1[1] - d2[1], d1[2] - d2[2])

    def comp(a):
        if a > 0:
            return date1
        elif a < 0:
            return date2
        else:
            return None

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
        logging.debug(f"Loaded last notice from {LAST_NOTICE}.")
    else:
        logging.debug(f"File {LAST_NOTICE} not found.")
        return None


def dump_last(notice):
    with open(LAST_NOTICE, 'w+') as fo:
        yaml.dump(notice, fo, Dumper=yaml.CDumper)
    logging.debug(f"Dumped '{notice['title'][:20]}' to {LAST_NOTICE}")


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
            logging.debug(f"Sending message to /sendMessage.")

            logging.getLogger().setLevel(logging.INFO)
            telegram_req = post(telegram_url, params=params)
            logging.getLogger().setLevel(logging.DEBUG)

            if telegram_req.status_code == 200:
                logging.info("Sucessfully send to /sendDocument.")
                return True
            else:
                logging.error(f"Recieved {telegram_req.status_code} http code from /sendDocument.")
                return False
        except ConnectionError:
            # logging.error(f"Connection Error- {ConnectionError} /sendDocument.")
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
            logging.debug(f"Sending file to /sendDocument.")

            logging.getLogger().setLevel(logging.INFO)
            telegram_req = post(telegram_url, data=data, files=files)
            logging.getLogger().setLevel(logging.DEBUG)

            if telegram_req.status_code == 200:
                logging.info("Sucessfully send to /sendDocument.")
                return True
            else:
                logging.error(f"Recieved {telegram_req.status_code} http code from /sendDocument.")
                return False
        except ConnectionError:
            # logging.error(f"Connection Error- {ConnectionError} /sendDocument.")
            pass
    return False


def main():
    try:
        logging.debug(f"Retriving {NOTICE_URL}.")
        
        html = get(NOTICE_URL).text
        # html = open('test.html', 'r').read()
        soup = bs.BeautifulSoup(html, 'lxml')

        n_gen = get_notices(soup)

        last_notice = load_last()

        # Get the New Notices
        notices = []
        for nt in n_gen:
            if nt != last_notice:
                logging.info(f"Found New Notice - {nt}")
                notices.append(nt)
            else:
                break

        for n in reversed(notices):
            logging.info(f"Sending {n}.")
            try:
                logging.info(f"Downloading notice file {n['url']} .")
                n_content = get(BASE_URL + n['url']).content
            except:
                logging.error("Failed to download file.")
                msg = f"{n['title']} \n    - [Download]({n['url']}) \n**Date:-** {n['date']}"
                res = send_msg(msg)
            else:
                logging.info(f"Download complete for {n['url']} .")
                msg = f"{n['title']} \n\nDate:- {n['date']}"
                res = send_file(msg, path.basename(n['url']), n_content)
            finally:
                if res:
                    dump_last(n)
                else:
                    logging.critical(f"Failed to send {n} after {T_API_RETRIES} retries.")
                          
    except Exception as ex:
        logging.fatal(str(ex))
        return



if __name__ == "__main__":
    logging.info("SCRIPT STARTED")
    main()
    logging.info("SCRIPT ENDED")
