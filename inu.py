#!/usr/bin/env python3
""" GGSIPU Tracker Script """

__version__ = "2.0.0-dev"

from os import path, environ, getcwd, makedirs
from logging import handlers, Formatter, StreamHandler, DEBUG, INFO, getLogger


import yaml
import bs4 as bs
from requests import post, get

LOG_PATH = 'inu.log'
UPLOAD_EXT = ('pdf', 'jpg', 'jpeg', 'png', 'ppt', 'pptx',
              'doc', 'docx', 'xls', 'xlsx', 'csv', 'zip', 'rar')


TG_CHAT = environ.get("TG_CHAT", "@ggsipu_notices")
BOT_TOKEN = environ['BOT_TOKEN']

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.16 Safari/537.36"
}


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
            '%(asctime)s %(levelname)-8s: %(funcName)s : %(message)s', datefmt='%m/%d/%Y %I:%M:%S %p')
        filehandler.setFormatter(fileformatter)
        logger.addHandler(filehandler)

    # Set up logging to the console.
    streamhandler = StreamHandler()
    streamhandler.setLevel(DEBUG)
    streamformatter = Formatter(
        '[%(levelname)s] %(funcName)s: %(message)s')
    streamhandler.setFormatter(streamformatter)
    logger.addHandler(streamhandler)

    return logger


def only_new_notice_tr(tag):
    return tag.name == 'tr' and not tag.has_attr('id') and not tag.has_attr('style')


def scrap_notice_tr(tr):
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

        # Remove newlines, extra whitespaces
        title = " ".join(notice_txt.split())

        return {"date": notice_date.strip(), "title": title, "url": dwd_url.strip()}
    else:
        return None


def get_notices(soup, url_prefix=""):
    f_trs = soup.tbody.find_all(only_new_notice_tr)
    for f_tr in f_trs:
        notice = scrap_notice_tr(f_tr)
        if notice:
            notice['url'] = url_prefix + notice['url']
            yield notice


def download_file(url, html_allow=False, headers=HEADERS, raise_ex=False):
    try:
        resp = get(url, headers=headers)
        if not resp.status_code == 200 or resp.content == None or (('text/html' in resp.headers['Content-Type']) & (not html_allow)):
            raise
        ret = resp.text if html_allow else resp.content
        return ret
    except Exception as ex:
        if raise_ex:
            raise ex
        return None


class InstanceReprMixin(type):
    def __repr__(self):
        return f'{self.__name__}'


class Dispatcher(metaclass=InstanceReprMixin):
    __dispatcher_name__ = 'BaseDispatcher'

    @classmethod
    def send(cls, notice, src):
        raise NotImplementedError


class Telegram(Dispatcher):
    __dispatcher_name__ = 'Telegram'

    _retries = T_API_RETRIES
    channel_id = TG_CHAT
    bot_token = BOT_TOKEN
    bot_endpoint = f"https://api.telegram.org/bot{bot_token}"

    @staticmethod
    def _escape_md2(text):
        return text.translate(str.maketrans({"_":  r"\_",
                                             "*":  r"\*",
                                             "[":  r"\[",
                                             "]":  r"\]",
                                             "(":  r"\(",
                                             ")":  r"\)",
                                             "~":  r"\~",
                                             "`":  r"\`",
                                             ">":  r"\>",
                                             "#":  r"\#",
                                             "+":  r"\+",
                                             "-":  r"\-",
                                             "=":  r"\=",
                                             "|":  r"\|",
                                             "{":  r"\{",
                                             "{":  r"\{",
                                             ",":  r"\,",
                                             ".":  r"\.",
                                             "!":  r"\!"
                                             }
                                            ))

    @classmethod
    def _post(cls, endpoint, **kwargs):
        return post(cls.bot_endpoint + endpoint, **kwargs)

    @classmethod
    def sendMessage(cls, msg, markdownv2=True, web_page_preview=False, reply_markup=None, **kwargs):
        data = {
            'chat_id': cls.channel_id,
            'text': msg,
            'disable_web_page_preview': not web_page_preview
        }
        if markdownv2:
            data['parse_mode'] = 'MarkdownV2'
        if reply_markup:
            data['reply_markup'] = reply_markup

        data.update(kwargs)
        return cls._post('/sendMessage', json=data)

    @classmethod
    def sendDocument(cls, fname, bfile, caption=None, markdownv2=True, **kwargs):
        files = {'document': (fname, bfile)}
        data = {
            'chat_id': TG_CHAT,
            'caption': caption,
            'parse_mode': "MarkdownV2" if markdownv2 else 'html'
        }
        data.update(kwargs)
        return cls._post('/sendDocument', data=data, files=files)

    @classmethod
    def send_msg_btn(cls, msg, btns):
        """btns: array of array of (title, url)"""
        reply_markup = {
            'inline_keyboard': [[{'text': btn[0], 'url':btn[1]} for btn in row] for row in btns]
        }
        return cls.sendMessage(msg, reply_markup=reply_markup).status_code == 200

    @classmethod
    def send_doc_from_url(cls, url, caption=None, markdownv2=True, **kwargs):
        return cls.sendDocument(None, url, caption, markdownv2, **kwargs).status_code == 200

    @classmethod
    def send(cls, notice, src):
        msg = f"\#{cls._escape_md2(src)}  \n*Date \- * {cls._escape_md2(notice['date'])} \n{cls._escape_md2(notice['title'])}"
        fname = path.basename(notice['url'])
        if fname.split('.')[-1].lower() in UPLOAD_EXT:
            if not cls.send_doc_from_url(notice['url'], caption=msg):
                # Try downloading and sending
                bfile = download_file(notice['url'])
                if bfile and cls.sendDocument(fname, bfile, msg).status_code == 200:
                    return True
                else:
                    return cls.send_msg_btn(msg, [[(f"Open - {fname}", notice['url'])]])
            else:
                return True
        else:
            return cls.send_msg_btn(msg, [[("Open Notice", notice['url'])]])


class Source(metaclass=InstanceReprMixin):
    __source_name__ = "BaseSource"
    _headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.116 Safari/537.36"
    }

    dispatchers = []
    base_url = None
    notice_url = None

    MAX_DUMP_SIZE = 15

    @classmethod
    def _raw_notice_gen(cls):
        html = download_file(
            cls.notice_url, html_allow=True, raise_ex=True)
        soup = bs.BeautifulSoup(html, 'lxml')
        return get_notices(soup, url_prefix=cls.base_url)

    @staticmethod
    def diff_notices_dicts(list1, list2):
        set_list1 = set(tuple(d.items()) for d in list1)
        set_list2 = set(tuple(d.items()) for d in list2)

        # Items in list1 not in list2
        differnce = set_list1 - set_list2
        diffs = []
        for elem in differnce:
            diffs.append(dict((x, y) for x, y in elem))
        # return sorted diff
        return [i for i in list1 if i in diffs]

    def __init__(self):
        self.dump_path = path.join('dump', self.__source_name__, 'dump.yml')
        self.failed_path = path.join(
            'dump', self.__source_name__, 'failed.yml')

        makedirs(path.dirname(self.dump_path), exist_ok=True)

        self.dump_notices = self._load_dnotices()

        self.failed_notices = []

    def __repr__(self):
        return f"{self.__source_name__}({self.notice_url})"

    def _load_yml(self, file):
        data = []
        if path.isfile(file):
            with open(file, 'r') as fr:
                data = yaml.load(fr, Loader=yaml.CLoader)
        data = data if data else []

        logger.debug(f"Load from {file} - {data}. Total - {len(data)}")
        return data

    def _dump_yml(self, data, file):
        logger.debug(f"Dumped into {file} - {data}")

        with open(file, 'w+') as fo:
            yaml.dump(data, fo, Dumper=yaml.CDumper)

    def _load_dnotices(self):
        return self._load_yml(self.dump_path)

    def _load_fnotices(self):
        return self._load_yml(self.failed_path)

    def _dump_notices(self):
        self._dump_yml(self.dump_notices[:self.MAX_DUMP_SIZE], self.dump_path)
        self._dump_yml(self.failed_notices, self.failed_path)

    def new_notices(self):
        return self.diff_notices_dicts(list(self._raw_notice_gen()), self.dump_notices)

    def dispatch_notice(self, notice):
        # return {"__target__name__":True,...}
        res_dict = {}
        for dispatcher in self.dispatchers:
            res_dict[dispatcher.__dispatcher_name__] = True
            logger.debug(
                f'Attempting to dispatch notice to {dispatcher.__dispatcher_name__}.')
            res = dispatcher.send(notice, self.__source_name__)
            if not res:
                logger.debug(
                    f'Failed to dispatch notice to {dispatcher.__dispatcher_name__}.')
                res_dict[dispatcher.__dispatcher_name__] = False
        return res_dict

    def send_new(self):
        notices = self.new_notices()
        logger.info(f"Found {notices} new notices. Total - {len(notices)}")

        for n in reversed(notices):
            logger.info(f'Sending {n}')
            res_dict = self.dispatch_notice(n)
            if True in res_dict.values():
                self.dump_notices.insert(0, n)
            else:
                n['dispatch'] = res_dict
                self.failed_notices.append(n)

        self._dump_notices()


class OfficialNotice(Source):
    __source_name__ = "OfficialNotice"
    dispatchers = [Telegram, ]
    base_url = 'http://www.ipu.ac.in'
    notice_url = base_url + '/notices.php'


class Hostel(Source):
    __source_name__ = "Hostel"
    dispatchers = [Telegram, ]
    base_url = 'http://www.ipu.ac.in'
    notice_url = base_url + '/hostels.php'


class Examination(Source):
    __source_name__ = "Examination"
    dispatchers = [Telegram, ]
    base_url = 'http://www.ipu.ac.in'
    notice_url = base_url + '/exam_notices.php'


def main(sources):
    try:
        for src in sources:
            logger.info(f"Processing New Notices for - {src}")
            src().send_new()
    except Exception as ex:
        logger.exception(str(ex))


if __name__ == "__main__":

    if PRODUCTION:
        logger = setupLogging(LOG_PATH, False)
        logger.info(f"SCRIPT STARTED (v{__version__}) [ON SERVER]")
    else:
        logger = setupLogging(LOG_PATH, True)
        logger.info(f"SCRIPT STARTED (v{__version__}) [LOCAL]")

    sources = [OfficialNotice, Hostel, Examination]
    logger.info(f"Notice Sources - {sources}")

    main(sources)
    logger.info(f"SCRIPT ENDED (v{__version__})")
