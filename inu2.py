#!/usr/bin/env python3
""" GGSIPU Tracker Script V2 """

__version__ = "2.0.0"


from collections import defaultdict
import logging
import logging.handlers
import os
import sys
from sys import path
import time
from dataclasses import dataclass, field, fields, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Set, Union, Iterator
from urllib.parse import urljoin
import bs4 as bs

import requests
import yaml
from yaml.resolver import BaseResolver

# use fast libYAML parsers if available
try:
    from yaml import CDumper as YAMLDumper
    from yaml import CLoader as YAMLLoader
except ImportError:
    from yaml import Dumper as YAMLDumper
    from yaml import Loader as YAMLLoader


CONFIG = None
TG_BOT_TOKEN = os.environ["TG_BOT_TOKEN"]


# setup logging
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

streamhandler = logging.StreamHandler()
streamformatter = logging.Formatter("[%(levelname)s] %(funcName)s: %(message)s")
streamhandler.setFormatter(streamformatter)
streamhandler.setLevel(logging.DEBUG)
logger.addHandler(streamhandler)

# UTILITY FUNCTIONS


def download_file(url, text_allow=False, headers=None, raise_ex=False):
    if not headers:
        headers = {
            "User-Agent": CONFIG.ua_agent
            if CONFIG
            else (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                "AppleWebKit/537.36 (KHTML, like Gecko)"
                "Chrome/80.0.3945.16 Safari/537.36"
            )
        }

    try:
        resp = requests.get(url, headers=headers)
        if (
            not resp.status_code == 200
            or resp.content == None
            or (("text/" in resp.headers["Content-Type"]) & (not text_allow))
        ):
            raise Exception(
                f"Error while downloading file, status_code={resp.status_code}"
            )
        ret = resp.text if text_allow else resp.content
        return ret
    except Exception as ex:
        if raise_ex:
            raise ex
        return None


# DATACLASSES


@dataclass(eq=True, frozen=True)
class NoticeContent:
    title: str
    date: date
    link: str


@dataclass
class Notice:
    content: NoticeContent
    sources: Set["Source"]

    @property
    def dispatchers(self) -> FrozenSet["Dispatcher"]:
        dps = []
        for source in self.sources:
            dps += source.dispatchers
        return frozenset(dps)


@dataclass
class Config:
    sources: List["Source"]
    ua_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        " AppleWebKit/537.36(KHTML, like Gecko)"
        " Chrome/80.0.3945.16 Safari/537.36"
    )
    max_dump: int = 50
    upload_extensions: FrozenSet[str] = frozenset(
        [
            "pdf",
            "jpg",
            "jpeg",
            "png",
            "ppt",
            "pptx",
            "doc",
            "docx",
            "xls",
            "xlsx",
            "csv",
            "zip",
            "rar",
        ]
    )


# CLASSES


class Dispatcher:
    pass


class Telegram(Dispatcher):
    name = "Telegram"

    def __init__(self, channel_id, upload_extensions) -> None:
        self.channel_id = channel_id
        self.upload_extensions = upload_extensions
        self.bot_endpoint = f"https://api.telegram.org/bot{TG_BOT_TOKEN}"

    def __getstate__(self):
        # will hide bot_endpoint and upload_extensions from yaml dump
        state = self.__dict__.copy()
        if state.get("bot_endpoint"):
            del state["bot_endpoint"]
        if state.get("upload_extensions"):
            del state["upload_extensions"]
        return state

    def __repr__(self) -> str:
        return f"<Telegram[{self.channel_id=}]>"

    @staticmethod
    def _escape_md2(text):
        return text.translate(
            str.maketrans(
                {
                    "_": r"\_",
                    "*": r"\*",
                    "[": r"\[",
                    "]": r"\]",
                    "(": r"\(",
                    ")": r"\)",
                    "~": r"\~",
                    "`": r"\`",
                    ">": r"\>",
                    "#": r"\#",
                    "+": r"\+",
                    "-": r"\-",
                    "=": r"\=",
                    "|": r"\|",
                    "{": r"\{",
                    "{": r"\{",
                    ",": r"\,",
                    ".": r"\.",
                    "!": r"\!",
                }
            )
        )

    def _post(self, endpoint, **kwargs):
        return requests.post(self.bot_endpoint + endpoint, **kwargs)

    def sendMessage(
        self, msg, markdownv2=True, web_page_preview=False, reply_markup=None, **kwargs
    ):
        data = {
            "chat_id": self.channel_id,
            "text": msg,
            "disable_web_page_preview": not web_page_preview,
        }
        if markdownv2:
            data["parse_mode"] = "MarkdownV2"
        if reply_markup:
            data["reply_markup"] = reply_markup

        data.update(kwargs)
        return self._post("/sendMessage", json=data)

    def sendDocument(self, fname, bfile, caption=None, markdownv2=True, **kwargs):
        files = {"document": (fname, bfile)}
        data = {
            "chat_id": self.channel_id,
            "caption": caption,
            "parse_mode": "MarkdownV2" if markdownv2 else "html",
        }
        data.update(kwargs)
        return self._post("/sendDocument", data=data, files=files)

    def send_msg_btn(self, msg, btns):
        """btns: array of array of (title, url)"""
        reply_markup = {
            "inline_keyboard": [
                [{"text": btn[0], "url": btn[1]} for btn in row] for row in btns
            ]
        }
        return self.sendMessage(msg, reply_markup=reply_markup).status_code == 200

    def send_doc_from_url(self, url, caption=None, markdownv2=True, **kwargs):
        return (
            self.sendDocument(None, url, caption, markdownv2, **kwargs).status_code
            == 200
        )

    def send(self, notice: Notice) -> bool:
        msg = (
            f"{self._escape_md2(' '.join(map(lambda x: f'#{x}', map(lambda x: x.name, notice.sources))))}  \n"
            f"*Date \- * {self._escape_md2(notice.content.date)} \n"
            f"{self._escape_md2(notice.content.title)}"
        )
        fname = os.path.basename(notice.content.link)
        if fname.split(".")[-1].lower() in self.upload_extensions:
            if not self.send_doc_from_url(notice.content.link, caption=msg):
                # Try downloading and sending
                bfile = download_file(notice.content.link)
                if bfile and self.sendDocument(fname, bfile, msg).status_code == 200:
                    return True
                else:
                    return self.send_msg_btn(
                        msg, [[(f"Open - {fname}", notice.content.link)]]
                    )
            else:
                return True
        else:
            return self.send_msg_btn(msg, [[("Open Notice", notice.content.link)]])


class Runner:
    def __init__(self, sources: List["Source"]) -> None:
        self.sources = sources

        # make failed path
        self.failed_path = Path("dump", "failed.yml")
        self.failed_path.parent.mkdir(exist_ok=True)
        self.failed_path.touch(exist_ok=True)

    def _dump_yml(self, data: Any, file: Union[Path, str], mode: str = "w") -> None:
        logger.debug(f"Dumped into {file} - {data}")

        with open(file, mode) as fo:
            yaml.dump(data, fo, Dumper=YAMLDumper)

    def get_new_notices(self) -> List[Notice]:
        # a dict to store Notice class as value with NoticeContent as key
        notice_dict: Dict[NoticeContent, Notice] = {}
        for src in self.sources:
            n_notices = src.new_notices()
            for nc in n_notices:
                # if NoticeContent is already present then
                # add the source to sources list
                if n := notice_dict.get(nc):
                    n.sources.add(src)
                else:
                    notice_dict[nc] = Notice(
                        nc,
                        set(
                            [
                                src,
                            ]
                        ),
                    )
        return list(notice_dict.values())

    def send_new(self) -> None:
        dump_dict: Dict[Source, List[Notice]] = defaultdict(list)
        failed_dict: Dict[NoticeContent, List[Dispatcher]] = defaultdict(list)
        for n in reversed(self.get_new_notices()):
            for dp in n.dispatchers:
                # try sending the notice
                if res := dp.send(n):
                    # if success then append to source specific
                    # list
                    for src in n.sources:
                        dump_dict[src].append(n)
                else:
                    # if failed append dispatcher to failed notices
                    # list
                    failed_dict[n.content].append(dp)

        for src, notices in dump_dict.items():
            notices.reverse()
            src.dump(notices)

        if len(failed_dict) > 0:
            self._dump_yml(
                [
                    {"content": asdict(c), "dispatchers": list(map(str, failed_dict[c]))}
                    for c in failed_dict
                ],
                self.failed_path,
                "a",
            )


class Source:
    def __init__(
        self, name: str, url: str, dispatchers: List[Dispatcher], max_dump: int = 50
    ) -> None:
        self.name = name
        self.url = url
        self.max_dump = max_dump
        self.dispatchers = dispatchers

        self.dump_path = Path("dump", f"{self.name}.yml")
        self.dump_path.parent.mkdir(exist_ok=True)
        self.dump_path.touch(exist_ok=True)

        self.dump_notices = self._load_dnotices()

    def __getstate__(self):
        # will hide attributes from yaml dump
        state = self.__dict__.copy()
        if state.get("dump_path"):
            del state["dump_path"]
        if state.get("dump_notices"):
            del state["dump_notices"]
        return state

    def __repr__(self) -> str:
        return f"<Source[{self.name=},{self.url=},{self.dispatchers=}, {self.max_dump=}]>"

    def _load_yml(self, file: Union[Path, str]) -> List:
        data = []
        with open(file, "r") as fr:
            data = yaml.load(fr, Loader=YAMLLoader)
        data = data if data else []

        logger.debug(f"Load from {file} - {data}. Total - {len(data)}")
        return data

    def _dump_yml(self, data: Any, file: Union[Path, str], mode: str = "w") -> None:
        logger.debug(f"Dumped into {file} - {data}")

        with open(file, mode) as fo:
            yaml.dump(data, fo, Dumper=YAMLDumper)

    def _load_dnotices(self):
        return [
            Notice(content=NoticeContent(**d["content"]), sources=d["sources"])
            for d in self._load_yml(self.dump_path)
        ]

    def dump(self, dnotices: List[Notice]):
        trim_notices = (dnotices + self.dump_notices)[: self.max_dump]
        # convert Notice.source to str to prevent duming object in yaml
        for n in trim_notices:
            n.sources = list(map(str, n.sources))

        self._dump_yml(
            [asdict(n) for n in trim_notices],
            self.dump_path,
        )

    @staticmethod
    def only_new_notice_tr(tag: bs.Tag) -> bool:
        return tag.name == "tr" and not tag.has_attr("id") and not tag.has_attr("style")

    @staticmethod
    def scrap_notice_tr(tr: bs.Tag, root_url: str) -> Union[NoticeContent, None]:
        tds = tr.find_all("td")
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

            # return {"date": notice_date.strip(), "title": title, "url": dwd_url.strip()}
            return NoticeContent(
                title=title,
                date=notice_date.strip(),
                link=urljoin(root_url, dwd_url.strip()),
            )
        else:
            return None

    def _get_notices_content(self, soup: bs.BeautifulSoup) -> Iterator[NoticeContent]:
        f_trs = soup.tbody.find_all(self.only_new_notice_tr)
        for f_tr in f_trs:
            if notice_content := self.scrap_notice_tr(f_tr, self.url):
                yield notice_content

    def all_notices(self, max_dump: int = None) -> List[NoticeContent]:
        if not max_dump:
            max_dump = self.max_dump
        html = download_file(self.url, text_allow=True, raise_ex=True)
        soup = bs.BeautifulSoup(html, "lxml")
        return list(self._get_notices_content(soup))[:max_dump]

    @staticmethod
    def diff_notices_dicts(list1: List[Dict], list2: List[Dict]) -> List[Dict]:
        """
        Items in list1 not in list2
        """
        set_list1 = set(tuple(d.items()) for d in list1)
        set_list2 = set(tuple(d.items()) for d in list2)

        # Items in list1 not in list2
        differnce = set_list1 - set_list2
        diffs = []
        for elem in differnce:
            diffs.append(dict((x, y) for x, y in elem))
        # return sorted diff
        return [i for i in list1 if i in diffs]

    def new_notices(self) -> List[NoticeContent]:
        all_notices = self.all_notices()
        # return sorted diff
        return [
            o for o in all_notices if o not in set(d.content for d in self.dump_notices)
        ]
        # return list(set(all_notices) - set(d.content for d in self.dump_notices))


DISPATCHER_MAPPING = {
    "telegram": Telegram,
}


def load_config(config_yaml: str) -> Config:
    """
    Load and parse the yaml config file and return Config object.
    """
    try:
        # parse yaml file
        config_dict = yaml.load(config_yaml, Loader=YAMLLoader)
    except yaml.ScannerError:
        logger.exception("Error while loading config file.")
    else:
        # Build the Source objects
        if sources_list := config_dict.get("notice_sources"):
            sources = []
            for sdict in sources_list:
                dispatchers = []
                for idx_disp in sdict["dispatchers"]:
                    upload_extensions = (
                        idx_disp.get("upload_extensions") or Config.upload_extensions
                    )
                    if isinstance(idx_disp, dict):
                        disp_name = next(iter(idx_disp))
                        disp = DISPATCHER_MAPPING[disp_name]
                        dispatchers.append(
                            disp(
                                # dict generator for make one dict out of list of dicts
                                # example:-
                                # [{1:2}, {'a':'b'}, {2:3}] --> {1:2, 'a':'b', 2:3}
                                **{
                                    k: v
                                    for d in idx_disp[disp_name]
                                    for k, v in d.items()
                                },
                                upload_extensions=upload_extensions,
                            )
                        )
                    elif isinstance(idx_disp, str):
                        dispatchers.append(
                            DISPATCHER_MAPPING[idx_disp](
                                upload_extensions=upload_extensions
                            )
                        )
                sources.append(
                    Source(
                        name=sdict["name"],
                        dispatchers=dispatchers,
                        url=sdict["url"],
                        max_dump=sdict.get("max_dump") or config_dict.get("max_dump") or Config.max_dump
                    )
                )
            return Config(
                sources=sources,
                **{
                    k: v
                    for k, v in config_dict.items()
                    if k in [f.name for f in fields(Config)]
                },
            )

        else:
            raise Exception(
                "`notice_sources` are required in config files. Please make sure to include it."
            )


# def load_config(config_yaml: str) -> Config:
#     def make_dispatchers(name, **kwargs):
#         return []


#     global_attr = {}
#     notice_sources = None
#     assert isinstance(yaml_data, dict)
#     for key, value in yaml_data.items():
#         if isinstance(value, (str, int, float, bool)):
#             global_attr[key] = value
#         elif key == "notice_sources":
#             notice_sources = value
#         else:
#             raise Exception(f"Unknown key {key} found in config.")
#     # check for notice_sources
#     if not isinstance(notice_sources, list):
#         raise Exception("`notice_source` are not defined properly in config")
#     # process noticce_sources
#     for elem in notice_sources:
#         name = elem["name"]
#         del elem["name"]

#         url = elem["url"]
#         del elem["url"]

#         max_dump = elem.get("max_dump") or global_attr.get("max_dump") or "DUMP"
#         if elem.get("max_dump"):
#             del elem["max_dump"]

#         dispatchers = make_dispatchers(elem["dispatchers"])
#         del elem["dispatchers"]


def main() -> int:
    global CONFIG
    try:
        # retrieve config
        config_file = os.environ.get("CONFIG_FILE") or "config.yml"
        if config_file.startswith("http"):
            logger.info(f"Downloading config file {config_file}")
            config_yaml = download_file(config_file, text_allow=True, raise_ex=True)
        else:
            config_yaml = None
            with open(config_file) as fp:
                logger.info(f"Reading config from {config_file}")
                config_yaml = fp.read()
        # load config
        CONFIG = load_config(config_yaml)

    except Exception:
        logger.exception(f"Error while loading config. Using default config.")
        return 1

    logger.info(f"Loaded config - {CONFIG}")

    # process new notices
    # Runner(CONFIG.sources).send_new()
    return 0


if __name__ == "__main__":
    start_time = time.time()
    logger.info(f"SCRIPT STARTED (v{__version__})")

    status = main()

    took_secs = time.time() - start_time
    logger.info(f"SCRIPT ENDED (v{__version__}). Took {took_secs} seconds.")

    sys.exit(status)
