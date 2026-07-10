# -------------------------------------------------------------------------------
#
# Name:        Quizlet plugin for Anki 2.0
# Purpose:     Import decks from Quizlet into Anki 2.0
# Author:
#  - Original: (c) Rolph Recto 2012, last updated 12/06/2012
#              https://github.com/rolph-recto/Anki-Quizlet
#  - Also:     Contributions from https://ankiweb.net/shared/info/1236400902
#  - Current:  JDMaybeMD
# Created:     04/07/2017
#
# Changlog:    Inital release
# * 2023-04-02 parser improvements
# * 2023-02-26 partial shapes support
# * 2022-10-30 add a proxy retry
# * 2022-05-15 add a rich text support
# * 2022-05-12 custom media folder fix (thx, https://github.com/mhujer)
# * 2022-04-20 add an "Add reverse" option
# * 2022-04-18 fix issue with original audio
# * 2022-04-17 fix issue with images/audio
# * 2022-04-10 fix mapping algorithm (thx, https://github.com/mhujer)
# * 2020-09-10 update audio download algorithm
# * 2020-09-08 have fixed audio download for special decks :)
# * 2020-09-06 have fixed a partial import. shame on me :)
# * 2020-09-05 made an audio download optional
# * 2020-09-05 update a quizlet parser

# -------------------------------------------------------------------------------
#!/usr/bin/env python

import re
import json
import urllib.parse
import requests
import webbrowser
import ssl
from aqt.utils import showText
from aqt.qt import *
from aqt import mw
import os
import sys
import logging
import urllib
from http.cookies import SimpleCookie
try:
    import urllib2
    URLError = urllib2.URLError
except Exception:
    import urllib.request as urllib2
    import urllib.error
    URLError = urllib.error.URLError
    
try:
    from PyQt6.QtCore import pyqtSignal
except Exception:
    from PyQt5.QtCore import pyqtSignal

ADDON_DIR = os.path.dirname(__file__)
VENDOR_DIR = os.path.join(ADDON_DIR, "vendor")

if os.path.isdir(VENDOR_DIR) and VENDOR_DIR not in sys.path:
    sys.path.insert(0, VENDOR_DIR)

# Suppress noisy TLS client loader logs ("Successfully loaded TLS library") so Anki doesn't treat them as errors. 
tls_logger = logging.getLogger("TLSLibrary")
tls_logger.setLevel(logging.ERROR)
tls_logger.propagate = False
if not tls_logger.handlers:
    tls_logger.addHandler(logging.NullHandler())

try:
    from tls_requests import get as tls_get, HTTPError as TLS_HTTP_ERROR
except ModuleNotFoundError:
    tls_get = requests.get
    from requests.exceptions import HTTPError as TLS_HTTP_ERROR

__window = None

# Anki
requests.packages.urllib3.disable_warnings()

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36"
}
TLS_IDENTIFIER = "chrome_120"

# Create an SSL context with certificate verification disabled
context = ssl.create_default_context()
context.check_hostname = False
context.verify_mode = ssl.CERT_NONE

# Install the SSL context globally
urllib2.install_opener(urllib2.build_opener(urllib2.HTTPSHandler(context=context)))

public_api_key = '0b8aa35d-b521-4fe0-bf0e-2ae07d826acf'


def get_cookies():
    config = mw.addonManager.getConfig(__name__)

    if config.get("qlts"):
        return {"qlts": config["qlts"]}

    if config.get("cookies"):
        cookie_parser = SimpleCookie()
        cookie_parser.load(config["cookies"])
        return {key: morsel.value for key, morsel in cookie_parser.items()}

    return {}

# add custom model if needed
def addCustomModel(col):

    # create custom model for imported deck
    mm = col.models
    existing = mm.by_name("Basic Quizlet Extended")
    if existing:
        return existing
    m = mm.new("Basic Quizlet Extended")

    # add fields
    mm.addField(m, mm.newField("FrontText"))
    mm.addField(m, mm.newField("FrontAudio"))
    mm.addField(m, mm.newField("BackText"))
    mm.addField(m, mm.newField("BackAudio"))
    mm.addField(m, mm.newField("Image"))
    mm.addField(m, mm.newField("Add Reverse"))

    # add cards
    t = mm.newTemplate("Normal")

    # front
    t['qfmt'] = "{{FrontText}}\n<br><br>\n{{FrontAudio}}"
    t['afmt'] = "{{FrontText}}\n<hr id=answer>\n{{BackText}}\n<br><br>\n{{Image}}\n<br><br>\n{{BackAudio}}"
    mm.addTemplate(m, t)

    # back
    t = mm.newTemplate("Reverse")
    t['qfmt'] = "{{#Add Reverse}}{{BackText}}\n<br><br>\n{{BackAudio}}{{/Add Reverse}}"
    t['afmt'] = "{{BackText}}\n<hr id=answer>\n{{FrontText}}\n<br><br>\n{{FrontAudio}}\n{{Image}}"
    mm.addTemplate(m, t)

    mm.add(m)
    return m

# throw up a window with some info (used for testing)

def debug(message):
    QMessageBox.information(QWidget(), "Message", message)

def getText(d, text=''):
    if d is None:
        return text
    if d['type'] == 'text':
        text = d['text']
        if 'marks' in d:
            for m in d['marks']:
                if m['type'] in ['b', 'i', 'u']:
                    text = '<{0}>{1}</{0}>'.format(m['type'], text)
                if 'attrs' in m:
                    attrs = " ".join(['{}="{}"'.format(k, v)
                                     for k, v in m['attrs'].items()])
                    text = '<span {}>{}</span>'.format(attrs, text)
        return text
    text = ''.join([getText(c) for c in d['content']]
                   ) if d.get('content') else ''
    if d['type'] == 'paragraph':
        text = '<div>{}</div>'.format(text)
    return text

def ankify(text):
    text = text.replace('\n', '<br>')
    text = text.replace('class="bgY"', 'style="background-color:#fff4e5;"')
    text = text.replace('class="bgB"', 'style="background-color:#cde7fa;"')
    text = text.replace('class="bgP"', 'style="background-color:#fde8ff;"')
    return text

class QuizletWindow(QWidget):
    # main window of Quizlet plugin
    def __init__(self):
        super(QuizletWindow, self).__init__()

        self.results = None
        self.thread = None
        self.config = mw.addonManager.getConfig(__name__)

        self.initGUI()

    # create GUI skeleton
    def initGUI(self):

        self.box_top = QVBoxLayout()
        self.box_upper = QHBoxLayout()

        # left side
        self.box_left = QVBoxLayout()
        self.check_boxes = QHBoxLayout()

        self.box_incoming_html = QHBoxLayout()
        self.box_incoming_html_left = QVBoxLayout()
        self.box_incoming_html_right = QHBoxLayout()

        self.value_incoming_html = QTextEdit("", self)
        self.value_incoming_html.setMinimumWidth(300)
        self.value_incoming_html.setPlaceholderText(
            """Enter page html if you constantly receive errors

1. Enter the url in 'Quizlet URL:'
2. Click 'Open html' (opens webpage)
3. Right-click, then click 'View page source'
4. Copy the all HTML and paste into 'Page html:'
5. Click 'Import Deck'

Note: 'Page html' does not support Quizlet folder import
""")

        self.label_incoming_html = QLabel("Page html:")
        self.label_incoming_html.setMinimumWidth(98)
        self.button_html = QPushButton("Open html", self)
        self.button_html.clicked.connect(self.onHmtl)

        self.box_incoming_html_left.addWidget(self.label_incoming_html)
        self.box_incoming_html_left.addWidget(self.button_html)
        self.box_incoming_html_left.addStretch()

        self.box_incoming_html_right.addWidget(self.value_incoming_html)
        self.box_incoming_html.addLayout(self.box_incoming_html_left)
        self.box_incoming_html.addLayout(self.box_incoming_html_right)

        # quizlet url field
        self.box_name = QHBoxLayout()
        self.label_url = QLabel("Quizlet URL or multiple URLS (separated with semicolon)")
        self.text_url = QLineEdit("", self)
        self.text_url.setMinimumWidth(300)
        self.text_url.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.text_url.setFocus()
        self.text_url.setToolTip(
            "Separate multiple deck URLs with a semicolon (;) to import them all at once.")

        self.label_url.setMinimumWidth(100)
        self.box_name.addWidget(self.label_url)
        self.box_name.addWidget(self.text_url)

        self.box_download_audio = QHBoxLayout()
        self.value_download_audio = QCheckBox("", self)
        self.label_download_audio = QLabel("Download audio:")
        self.value_download_audio.toggle()
        self.label_download_audio.setMinimumWidth(100)
        self.box_download_audio.addWidget(self.label_download_audio)
        self.box_download_audio.addWidget(self.value_download_audio)

        self.box_add_reverse = QHBoxLayout()
        self.value_add_reverse = QCheckBox("", self)
        self.label_add_reverse = QLabel("Add reverse:")
        self.box_add_reverse.addWidget(self.label_add_reverse)
        self.box_add_reverse.addWidget(self.value_add_reverse)

        self.box_skip_errors = QHBoxLayout()
        self.value_skip_errors = QCheckBox("", self)
        self.value_skip_errors.toggle()
        self.value_skip_errors.setToolTip(
            'Will skip audio/images download errors (recommend: Enabled)')
        self.label_skip_errors = QLabel("Skip errors:")
        self.label_skip_errors.setToolTip(
            'Will skip audio/images download errors (recommend: Enabled)')
        self.box_skip_errors.addWidget(self.label_skip_errors)
        self.box_skip_errors.addWidget(self.value_skip_errors)

        self.box_start_phrase = QHBoxLayout()
        self.value_start_phrase = QLineEdit("", self)
        self.value_start_phrase.setMinimumWidth(300)
        self.value_start_phrase.setPlaceholderText(
            'Start from this phrase. Can be empty')
        self.label_start_phrase = QLabel("Start Phrase:")
        self.label_start_phrase.setMinimumWidth(100)
        self.box_start_phrase.addWidget(self.label_start_phrase)
        self.box_start_phrase.addWidget(self.value_start_phrase)

        self.box_stop_phrase = QHBoxLayout()
        self.value_stop_phrase = QLineEdit("", self)
        self.value_stop_phrase.setMinimumWidth(300)
        self.value_stop_phrase.setPlaceholderText(
            'Stop after this phrase. Can be empty')
        self.label_stop_phrase = QLabel("Stop Phrase:")
        self.label_stop_phrase.setMinimumWidth(100)
        self.box_stop_phrase.addWidget(self.label_stop_phrase)
        self.box_stop_phrase.addWidget(self.value_stop_phrase)

        # add layouts to left
        self.box_left.addLayout(self.box_name)
        self.box_left.addLayout(self.check_boxes)
        self.check_boxes.addLayout(self.box_download_audio)
        self.check_boxes.addLayout(self.box_add_reverse)
        self.check_boxes.addLayout(self.box_skip_errors)
        self.check_boxes.addStretch()

        self.box_left.addLayout(self.box_start_phrase)
        self.box_left.addLayout(self.box_stop_phrase)
        self.box_left.addLayout(self.box_incoming_html)

        # right side
        self.box_right = QVBoxLayout()

        # code (import set) button
        self.box_code = QVBoxLayout()
        self.button_code = QPushButton("Import multi Deck", self)
        # self.box_code.addStretch(1)
        self.box_code.addWidget(self.button_code)
        self.button_code.clicked.connect(self.onImportClicked)

        # add layouts to right
        self.box_right.addLayout(self.box_code)
        self.box_right.addStretch()

        # add left and right layouts to upper
        self.box_upper.addLayout(self.box_left)
        self.box_upper.addSpacing(20)
        self.box_upper.addLayout(self.box_right)

        # results label and FAQ button
        self.label_results = QLabel(
            "\r\n<i>Example: https://quizlet.com/150875612/usmle-flash-cards/</i>")
        self.button_faq = QPushButton("FAQ", self)
        self.button_faq.clicked.connect(self.onFaq)

        self.box_results = QHBoxLayout()
        self.box_results.addWidget(self.label_results)
        self.box_results.addStretch()
        self.box_results.addWidget(self.button_faq)

        # add all widgets to top layout
        self.box_top.addLayout(self.box_upper)
        self.box_top.addLayout(self.box_results)
        self.box_top.addStretch(1)
        self.setLayout(self.box_top)

        # go, baby go!
        self.setMinimumWidth(600)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        self.setWindowTitle("Improved Quizlet to Anki Importer")
        self.show()

    def onHmtl(self):
        """
        Opens the flascards html page in a browser
        """
        urls = self.getQuizletUrls()

        if not urls:
            self.label_results.setText("Oops! You forgot the deck URL :(")
            return

        quizletDeckID = self.getQuizletDeckID(urls[0])

        if quizletDeckID == None:
            return

        webbrowser.open(
            "https://quizlet.com/{}/flashcards".format(quizletDeckID))

    def onFaq(self):
        webbrowser.open(
            "https://github.com/sviatoslav-lebediev/anki-quizlet-importer-extended/wiki/FAQ")

    def getQuizletUrls(self):
        # multiple deck URLs can be entered separated by a semicolon
        return [u.strip() for u in self.text_url.text().split(';') if u.strip()]

    def getQuizletDeckID(self, url=None):
        # grab url input
        if url is None:
            url = self.text_url.text()

        # voodoo needed for some error handling
        if urllib.parse.urlparse(url).scheme:
            urlDomain = urllib.parse.urlparse(url).netloc
        else:
            urlDomain = urllib.parse.urlparse("https://"+url).netloc

        # validate quizlet URL
        if url == "":
            self.label_results.setText("Oops! You forgot the deck URL :(")
            return
        elif not "quizlet.com" in urlDomain:
            self.label_results.setText("Oops! That's not a Quizlet URL :(")
            return


        # voodoo needed for some error handling
        if urllib.parse.urlparse(url).scheme:
            urlPath = urllib.parse.urlparse(url).path
        else:
            urlPath = urllib.parse.urlparse("https://"+url).path
        # validate and set Quizlet deck ID
        quizletDeckID = urlPath.strip("/")



        if quizletDeckID == "":
            self.label_results.setText("Oops! Please use the full deck URL :(")
            return
        elif re.search(r'user/', quizletDeckID) and re.search(r'/folders', quizletDeckID):
            match_full = re.match(r'user/[^/]+/folders/[^/]*', quizletDeckID)
            if not match_full:
                self.label_results.setText("Oops! Invalid Folder URL")
                return
            else:
                self.label_results.setText("Going to import a folder !")
                quizletDeckID = 'folder'
                return quizletDeckID
        elif not bool(re.search(r'\d', quizletDeckID)):
            self.label_results.setText(
                "Oops! No deck ID found in path <i>{0}</i> :(".format(quizletDeckID))
            return
        else:  # get first set of digits from url path
            quizletDeckID = re.search(r"\d+", quizletDeckID).group(0)


        return quizletDeckID

    def FolderExtract(self, page_html):
            # Extract studyMaterialId values from the page HTML
            ids = re.findall(r'"studyMaterialId":"(\d+)"', page_html)
            for id in ids:
                #url = "https://quizlet.com/{}/flashcards".format(id)
                self.label_results.setText(f'Downloading deck {ids.index(id)+1}/{len(ids)}')
                quizletDeckID = id
                self.onCode(quizletDeckID)

    def onImportClicked(self):
        urls = self.getQuizletUrls()
        self.label_results.setText("[QuizletImporter] parsed {0} url(s): {1}".format(len(urls), urls))

        if not urls:
            self.label_results.setText("Oops! You forgot the deck URL :(")
            return

        imported = 0

        for index, url in enumerate(urls):
            if len(urls) > 1:
                self.label_results.setText(
                    "Connecting to Quizlet... (deck {0}/{1})".format(index + 1, len(urls)))
                mw.app.processEvents()

            try:
                quizletDeckID = self.getQuizletDeckID(url)
                if quizletDeckID == None:
                    continue

                if self.onCode(quizletDeckID, url):
                    imported += 1
            except Exception as e:
                print("[QuizletImporter] Error importing {0}: {1!r}".format(url, e))
                self.label_results.setText(
                    "Error importing deck {0}/{1}: {2}".format(index + 1, len(urls), e))
                mw.app.processEvents()

        if len(urls) > 1:
            self.label_results.setText(
                "Finished importing {0}/{1} decks".format(imported, len(urls)))

    def onCode(self, quizletDeckID, url=None):
        html = self.value_incoming_html.toPlainText()

        if type(quizletDeckID) != int:
            if quizletDeckID == None:
                return False
            elif quizletDeckID == 'folder':
                deck_url = url if url is not None else self.text_url.text()
            else:
                # build URL
                deck_url = "https://quizlet.com/{}/flashcards".format(quizletDeckID)
        else:
            deck_url = "https://quizlet.com/{}/flashcards".format(quizletDeckID)

        # and aaawaaaay we go...


        # download the data!
        try:
            thread = QuizletDownloader(self, deck_url, quizletDeckID, html)
            # Connect the signal so that FolderExtract is called in the main thread:
            thread.folderExtracted.connect(self.FolderExtract)
            thread.start()
        except Exception as e:
            thread = None

        if thread is not None:
            while not thread.isFinished():
                mw.app.processEvents()
                thread.wait(50)
        else:
            self.label_results.setText("Error: Thread not initialized.")

        # error fetching data
        success = False
        if thread and thread.error:
            if thread.errorCode == 403:
                if thread.errorCaptcha:
                    self.label_results.setText(
                        "Sorry, it's behind a captcha. Try to disable VPN")
                else:
                    self.label_results.setText(
                        "Sorry, this is a private deck :(")
            elif thread.errorCode == 404:
                self.label_results.setText(
                    "Can't find a deck with the ID <i>{0}</i>".format(quizletDeckID))
            else:
                self.label_results.setText("Unknown Error")
                showText(thread.errorMessage)
        else:  # everything went through, let's roll!
            if quizletDeckID != 'folder':
                deck = thread.results
                self.label_results.setText(
                    ("Importing deck {0}...".format(deck["title"])))
                self.createDeck(deck)
                self.label_results.setText(
                    ("Success! Imported <b>{0}</b> ({1} cards)".format(deck["title"], deck["term_count"])))
            success = True

        if thread and thread.isRunning():
            thread.quit()
            thread.wait()

        return success

    def createDeck(self, result):
        # create new deck and custom model
        if "set" in result:
            name = result['set']['title']
        elif "studyable" in result:
            name = result['studyable']['title']
        else:
            name = result['title']

        items = result['items']
        progress = 0

        result['term_count'] = len(items)

        deck = mw.col.decks.get(mw.col.decks.id(name))
        model = addCustomModel(mw.col)

        # assign custom model to new deck
        mw.col.decks.select(deck["id"])
        mw.col.decks.save(deck)

        # assign new deck to custom model
        mw.col.models.set_current(model)
        model["did"] = deck["id"]
        mw.col.models.save(model)

        startProcess = False
        stopProcess = False
        startPhrase = self.value_start_phrase.text()
        stopPhrase = self.value_stop_phrase.text()
        downloadAudio = self.value_download_audio.isChecked()
        addReverse = self.value_add_reverse.isChecked()

        for item in items:
            if "".__eq__(startPhrase) or startPhrase == item["term"] or startPhrase == item["definition"]:
                startProcess = True

            if not stopProcess and startProcess:
                note = mw.col.newNote()
                note["FrontText"] = item["term"]
                note["BackText"] = item["definition"]
                note["FrontText"] = ankify(note["FrontText"])
                note["BackText"] = ankify(note["BackText"])

                if item.get('termAudio') and downloadAudio:
                    file_name = self.fileDownloader(self.getAudioUrl(
                        item['termAudio']), str(item["id"]) + "-front.mp3", fallback=True)
                    if file_name:
                        note["FrontAudio"] = "[sound:" + file_name + "]"

                if item.get('definitionAudio') and downloadAudio:
                    file_name = self.fileDownloader(self.getAudioUrl(
                        item["definitionAudio"]), str(item["id"]) + "-back.mp3", fallback=True)
                    if file_name:
                        note["BackAudio"] = "[sound:" + file_name + "]"

                if item.get('imageUrl'):
                    file_name = self.fileDownloader(item["imageUrl"], fallback=True)
                    if file_name:
                        note["Image"] += '<div><img src="{0}"></div>'.format(
                            file_name)

                    mw.app.processEvents()

                if addReverse:
                    note["Add Reverse"] = "True"

                mw.col.addNote(note)

                progress += 1
                self.label_results.setText(
                    ("Imported {0}/{1}".format(progress, len(items))))
                mw.app.processEvents()

            if not "".__eq__(stopPhrase) and (stopPhrase == item["term"] or stopPhrase == item["definition"]):
                stopProcess = True

        mw.col.reset()
        mw.reset()

    def getAudioUrl(self, word_audio):
        return word_audio if word_audio.startswith('http') else "https://quizlet.com/{0}".format(word_audio)

    # download the images
    def fileDownloader(self, url, suffix='', fallback=False):
        skip_errors = self.value_skip_errors.isChecked()
        url = url.replace('_m', '')
        file_name = "quizlet-" + \
            suffix if suffix else "quizlet-" + url.split('/')[-1]
        fallback_call = False;
        request_headers = headers.copy()

        while True:
            try:
                return download_media(url, file_name, request_headers)
            except (urllib2.HTTPError, URLError, TLS_HTTP_ERROR) as e:
                if fallback and not fallback_call:
                    fallback_call = True
                    url = "https://quizlet-proxy.proto.click/quizlet-media?url={0}".format(urllib.parse.quote(url))
                    request_headers["x-api-key"] = self.config.get("license", public_api_key)
                    continue
                if skip_errors:
                    return None
                else:
                    error_code = getattr(e, 'code', None)
                    if error_code:
                        debug(f"throwing exception {error_code}")
                    else:
                        debug(f"throwing exception {e}")
                    raise e


def download_media (url, file_name, headers):
    cookies = get_cookies()
    r = tls_get(url, tls_identifier=TLS_IDENTIFIER, headers=headers, cookies=cookies)
    status_code = r.status_code if hasattr(r, "status_code") else r.getcode()
    if status_code == 200:
        body = r.content if hasattr(r, "content") else r.read()
        with open(mw.col.media.dir() + "/" + file_name, 'wb') as f:
            f.write(body)
    return file_name

def parseTextItem(item):
    return getText(item["richText"], item["plainText"])


def mapItems(studiableItems, setIdToDiagramImage=None):
    result = []

    for studiableItem in studiableItems:
        image = None
        term = None
        term_audio = None
        definition = None
        definition_audio = None

        for side in studiableItem["cardSides"]:
            if (side["label"] == "word"):
                for media in side["media"]:
                    if media["type"] == 4:
                        term_audio = media["url"]

                    if media["type"] == 1:
                        term = parseTextItem(media)

                        if media["ttsUrl"] and term_audio == None:
                            term_audio = media["ttsUrl"]

            if (side["label"] == "definition"):
                for media in side["media"]:
                    if media["type"] == 4:
                        definition_audio = media["url"]

                    if media["type"] == 1:
                        definition = parseTextItem(media)

                        if media["ttsUrl"] and definition_audio == None:
                            definition_audio = media["ttsUrl"]

                    if (media["type"] == 2) and (image == None):
                        image = media["url"]

            # partial shape support
            if (side["label"] == "location"):
                for media in side["media"]:
                    if (media["type"] == 5) and (image == None):
                        image = setIdToDiagramImage[str(
                            studiableItem["studiableContainerId"])]["url"]

        result.append({
            "id": studiableItem["id"],
            "term": term,
            "termAudio": term_audio,
            "definition": definition,
            "definitionAudio": definition_audio,
            "imageUrl": image
        })

    return result


class QuizletDownloader(QThread):
    # thread that downloads results from the Quizlet API
    folderExtracted = pyqtSignal(str)

    def __init__(self, window, url, quizletDeckID, html):
        super(QuizletDownloader, self).__init__()
        self.window = window
        self.url = url
        self.results = None
        self.html = html
        self.quizletDeckID = quizletDeckID

        self.error = False
        self.errorCode = None
        self.errorCaptcha = False
        self.errorReason = None
        self.errorMessage = None

    def getDataFromApi(self):
        try:
            deckUrl = 'https://quizlet.com/webapi/3.9/sets/{0}'.format(
                self.quizletDeckID)
            # TODO download more than 1000 items
            itemsUrl = 'https://quizlet.com/webapi/3.9/studiable-item-documents?filters%5BstudiableContainerId%5D={0}&filters%5BstudiableContainerType%5D=1&perPage={1}&page=1'.format(
                self.quizletDeckID, 1000)

            deckResponse = requests.get(deckUrl, verify=False, headers=headers)
            itemsResponse = requests.get(
                itemsUrl, verify=False, headers=headers)

            rawJson = {"studiableDocumentData": json.loads(
                itemsResponse.text)["responses"][0]["models"]}

            items = mapItems(rawJson)
            title = json.loads(deckResponse.text)["responses"][
                0]['models']['set'][0]['title']

            self.results = {}
            self.results['items'] = items
            self.results['title'] = title
        except Exception as e:
            self.error = True
            self.errorMessage = "{}\n-----------------\n{}".format(
                e, itemsResponse.text)

    def getDataFromPage(self):
        proxyRetry = True

        while True:
            try:
                r = None
                cookies = get_cookies()

                page_html = ''

                if self.quizletDeckID == 'folder':
                    url = self.url if proxyRetry else 'https://quizlet-proxy.proto.click/quizlet-folders?url=' + \
                        urllib.parse.quote(self.url, safe='()*!\'')
                    r = tls_get(url, tls_identifier=TLS_IDENTIFIER, headers=headers, cookies=cookies)
                    r.raise_for_status()
                    page_html = r.text
                    self.folderExtracted.emit(page_html)
                else:
                    if self.html:
                        page_html = self.html
                    else:
                        url = self.url if proxyRetry else 'https://quizlet-proxy.proto.click/quizlet-deck?url=' + \
                            urllib.parse.quote(self.url, safe='()*!\'')
                        print(url)
                        r = tls_get(url, tls_identifier=TLS_IDENTIFIER, headers=headers, cookies=cookies)
                        r.raise_for_status()
                        page_html = r.text

                    regex = re.escape('window.Quizlet["setPasswordData"]')

                    if re.search(regex, page_html):
                        if (proxyRetry):
                            proxyRetry = False
                            continue

                        self.error = True
                        self.errorCode = 403
                        return

                    regex = re.escape('window.Quizlet["setPageData"] = ')
                    regex += r'(.+?)'
                    regex += re.escape('; QLoad("Quizlet.setPageData");')
                    m = re.search(regex, page_html)

                    studiableItems = None
                    setIdToDiagramImage = None

                    if not m:
                        regex = re.escape('window.Quizlet["assistantModeData"] = ')
                        regex += r'(.+?)'
                        regex += re.escape('; QLoad("Quizlet.assistantModeData");')
                        m = re.search(regex, page_html)
                        if m:
                            data = json.loads(m.group(1).strip())
                            studiableDocumentData = data['studiableDocumentData']
                            setIdToDiagramImage = studiableDocumentData.get(
                                'setIdToDiagramImage', None)
                            studiableItems = studiableDocumentData.get(
                                'studiableItems', studiableDocumentData.get('studiableItem'))

                    if not m:
                        regex = re.escape('window.Quizlet["cardsModeData"] = ')
                        regex += r'(.+?)'
                        regex += re.escape('; QLoad("Quizlet.cardsModeData");')
                        m = re.search(regex, page_html)
                        if m:
                            data = json.loads(m.group(1).strip())
                            studiableDocumentData = data['studiableDocumentData']
                            setIdToDiagramImage = studiableDocumentData.get(
                                'setIdToDiagramImage', None)
                            studiableItems = studiableDocumentData.get(
                                'studiableItems', studiableDocumentData.get('studiableItem'))

                    if not m:
                        regex = re.escape('dehydratedReduxStateKey":')
                        regex += r'(.+?)'
                        regex += re.escape('},"__N_SSP')
                        m = re.search(regex, page_html)
                        if m:
                            rawData = m.group(1).strip()
                            data = json.loads(json.loads(rawData))
                            studiableItems = data["studyModesCommon"]["studiableData"]["studiableItems"]
                            setIdToDiagramImage = data["studyModesCommon"]["studiableData"]["setIdToDiagramImage"]
                        else:
                            raise Exception("Can't extract data")

                    self.results = {}
                    self.results['items'] = mapItems(
                        studiableItems, setIdToDiagramImage)

                    title = os.path.basename(
                        self.url.strip()) or "Quizlet Flashcards"

                    m = re.search(r'<title[^>]*>(.+?)</title>', page_html, re.IGNORECASE | re.DOTALL)

                    if m:
                        title = m.group(1)
                        title = re.sub(r' \| Quizlet$', '', title)
                        title = re.sub(r'^Flashcards ', '', title)
                        title = re.sub(r'\s+', ' ', title)
                        title = title.strip()

                    self.results['title'] = title

            except TLS_HTTP_ERROR as e:
                if proxyRetry == True:
                    proxyRetry = False
                    continue
                else:
                    self.error = True
                    self.errorCode = e.response.status_code
                    self.errorMessage = e.response.text
                    if "CF-Chl-Bypass" in e.response.headers:
                        self.errorCaptcha = True
            except ValueError as e:
                if proxyRetry == True:
                    continue
                else:
                    self.error = True
                    self.errorMessage = "Invalid json1: {0}".format(e)
            except Exception as e:
                if proxyRetry == True and not self.html:
                    proxyRetry = False
                    continue
                else:
                    self.error = True
                    self.errorMessage = "{}\n-----------------\n{}".format(
                        e, page_html)
            break
        # yep, we got it

    def run(self):
        self.getDataFromPage()

        if (self.error):
            self.getDataFromApi()

# plugin was called from Anki


def runQuizletPlugin():
    global __window
    __window = QuizletWindow()


# create menu item in Anki
action = QAction("Import from Quizlet multi urls supported ", mw)
action.triggered.connect(runQuizletPlugin)
mw.form.menuTools.addAction(action)
