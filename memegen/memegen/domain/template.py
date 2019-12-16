import os
import hashlib
import shutil
from pathlib import Path
from contextlib import suppress
import tempfile

import requests
from PIL import Image
import log

from .text import Text


DEFAULT_REQUEST_HEADERS = {
    'User-Agent': "Googlebot/2.1 (+http://www.googlebot.com/bot.html)",
}


class Template:
    """Blank image to generate a meme."""

    DEFAULT = 'default'
    EXTENSIONS = ('.png', '.jpg')

    SAMPLE_LINES = ["YOUR TEXT", "GOES HERE"]

    VALID_LINK_FLAG = '.valid_link.tmp'

    MIN_HEIGHT = 240
    MIN_WIDTH = 240

    def __init__(self, key, name=None, lines=None, aliases=None, link=None,
                 root=None):
        self.key = key
        self.name = name or ""
        self.lines = lines or [""]
        self.aliases = aliases or []
        self.link = link or ""
        self.root = root or ""

    def __str__(self):
        return self.key

    def __eq__(self, other):
        return self.key == other.key

    def __ne__(self, other):
        return self.key != other.key

    def __lt__(self, other):
        return self.name < other.name

    @property
    def dirpath(self):
        return os.path.join(self.root, self.key)

    @property
    def path(self):
        return self.get_path()

    @property
    def default_text(self):
        return Text(self.lines)

    @property
    def default_path(self):
        return self.default_text.path or Text.EMPTY

    @property
    def sample_text(self):
        return self.default_text or Text(self.SAMPLE_LINES)

    @property
    def sample_path(self):
        return self.sample_text.path

    @property
    def aliases_lowercase(self):
        return [self.strip(a, keep_special=True) for a in self.aliases]

    @property
    def aliases_stripped(self):
        return [self.strip(a, keep_special=False) for a in self.aliases]

    @property
    def styles(self):
        return sorted(self._styles())

    def _styles(self):
        """Yield all template style names."""
        for filename in os.listdir(self.dirpath):
            name, ext = os.path.splitext(filename.lower())
            if ext in self.EXTENSIONS and name != self.DEFAULT:
                yield name

    @property
    def keywords(self):
        words = set()
        for fields in [self.key, self.name] + self.aliases + self.lines:
            for word in fields.lower().replace(Text.SPACE, ' ').split(' '):
                if word:
                    words.add(word)
        return words

    @staticmethod
    def strip(text, keep_special=False):
        text = text.lower().strip().replace(' ', '-')
        if not keep_special:
            for char in ('-', '_', '!', "'"):
                text = text.replace(char, '')
        return text

    def get_path(self, style_or_url=None, *, download=True):
        path = None

        if style_or_url and '://' in style_or_url:
            if download:
                path = download_image(style_or_url)
                if path is None:
                    path = self._find_path_for_style(self.DEFAULT)

        else:
            names = [n.lower() for n in [style_or_url, self.DEFAULT] if n]
            path = self._find_path_for_style(*names)

        return path

    def _find_path_for_style(self, *names):
        for name in names:
            for extension in self.EXTENSIONS:
                path = Path(self.dirpath, name + extension)
                with suppress(OSError):
                    if path.is_file():
                        return path
        return None

    def search(self, query):
        """Count the number of times a query exists in relevant fields."""
        if query is None:
            return -1

        count = 0

        for field in [self.key, self.name] + self.aliases + self.lines:
            count += field.lower().count(query.lower())

        return count

    def validate(self, validators=None):
        if validators is None:
            validators = [
                self.validate_meta,
                self.validate_link,
                self.validate_size,
            ]
        for validator in validators:
            if not validator():
                return False
        return True

    def validate_meta(self):
        if not self.lines:
            self._error("has no default lines of text")
            return False
        if not self.name:
            self._error("has no name")
            return False
        if not self.name[0].isalnum():
            self._error(f"name '{self.name}' should start with alphanumeric")
            return False
        if not self.path:
            self._error("has no default image")
            return False
        return True

    def validate_link(self):
        if not self.link:
            return True

        flag = Path(self.dirpath, self.VALID_LINK_FLAG)
        with suppress(IOError):
            with flag.open() as f:
                if f.read() == self.link:
                    log.info(f"Link already checked: {self.link}")
                    return True

        log.info(f"Checking link {self.link}")
        try:
            response = requests.head(self.link, timeout=5,
                                     headers=DEFAULT_REQUEST_HEADERS)
        except requests.exceptions.ReadTimeout:
            log.warning("Connection timed out")
            return True  # assume URL is OK; it will be checked again

        if response.status_code in [403, 429]:
            self._warn(f"link is unavailable ({response.status_code})")
        elif response.status_code >= 400:
            self._error(f"link is invalid ({response.status_code})")
            return False

        with flag.open('w') as f:
            f.write(self.link)
        return True

    def validate_size(self):
        im = Image.open(self.path)
        w, h = im.size
        if w < self.MIN_WIDTH or h < self.MIN_HEIGHT:
            log.error("Image must be at least "
                      f"{self.MIN_WIDTH}x{self.MIN_HEIGHT} (is {w}x{h})")
            return False
        return True

    def _warn(self, message):
        log.warning(f"Template '{self}' " + message)

    def _error(self, message):
        log.error(f"Template '{self}' " + message)


class Placeholder:
    """Default image for missing templates."""

    FALLBACK_PATH = str(Path(__file__)
                        .parents[1]
                        .joinpath('static', 'images', 'missing.png'))

    path = None

    def __init__(self, key):
        self.key = key

    @classmethod
    def get_path(cls, url=None, download=True):
        path = None

        if url and download:
            path = download_image(url)

        if path is None:
            path = cls.FALLBACK_PATH

        return path


def download_image(url):
    if not url or '://' not in url:
        raise ValueError(f"Not a URL: {url!r}")

    path = Path(tempfile.gettempdir(),
                hashlib.md5(url.encode('utf-8')).hexdigest())

    if path.is_file():
        log.debug(f"Already downloaded: {url}")
        return path

    try:
        response = requests.get(url, stream=True, timeout=5,
                                headers=DEFAULT_REQUEST_HEADERS)
    except ValueError:
        log.error(f"Invalid link: {url}")
        return None
    except requests.exceptions.RequestException:
        log.error(f"Bad connection: {url}")
        return None

    if response.status_code == 200:
        log.info(f"Downloading {url}")
        with open(str(path), 'wb') as outfile:
            response.raw.decode_content = True
            shutil.copyfileobj(response.raw, outfile)
        return path

    log.error(f"Unable to download: {url}")
    return None
