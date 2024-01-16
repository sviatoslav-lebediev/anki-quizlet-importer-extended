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
from aqt.utils import showText
from aqt.qt import *
from aqt import mw
from operator import itemgetter
import urllib
try:
    import urllib2
except Exception:
    import urllib.request as urllib2

__window = None

# Anki
requests.packages.urllib3.disable_warnings()

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36"
}

# add custom model if needed


def addCustomModel(name, col):

    # create custom model for imported deck
    mm = col.models
    existing = mm.byName("Basic Quizlet Extended")
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

1.Enter the url
2.Click on the 'Open page' button
3.Right click, 'View page source'
4.Copy the html
5.If you don't need audio, uncheck the box
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
        self.label_url = QLabel("Quizlet URL:")
        self.text_url = QLineEdit("", self)
        self.text_url.setMinimumWidth(300)
        self.text_url.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.text_url.setFocus()

        self.label_url.setMinimumWidth(100)
        self.box_name.addWidget(self.label_url)
        self.box_name.addWidget(self.text_url)

        self.box_download_audio = QHBoxLayout()
        self.value_download_audio = QCheckBox("", self)
        self.value_download_audio.toggle()
        self.label_download_audio = QLabel("Download audio:")
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
        self.value_skip_errors.setToolTip(
            'Will skip audio/images download errors')
        self.label_skip_errors = QLabel("Skip errors:")
        self.label_skip_errors.setToolTip(
            'Will skip audio/images download errors')
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
        self.button_code = QPushButton("Import Deck", self)
        self.discussion_button = QPushButton("Audio fix discussion")
        self.discussion_button.clicked.connect(self.onDiscussion)
        self.discussion_button.setStyleSheet("QPushButton { text-align: left; color: #087FFF; text-decoration: underline; border: none; }")
        # self.box_code.addStretch(1)
        self.box_code.addWidget(self.button_code)
        self.box_code.addWidget(self.discussion_button)
        self.button_code.clicked.connect(self.onCode)

        # add layouts to right
        self.box_right.addLayout(self.box_code)
        self.box_right.addStretch()

        # add left and right layouts to upper
        self.box_upper.addLayout(self.box_left)
        self.box_upper.addSpacing(20)
        self.box_upper.addLayout(self.box_right)

        # results label
        self.label_results = QLabel(
            "\r\n<i>Example: https://quizlet.com/150875612/usmle-flash-cards/</i>")

        # add all widgets to top layout
        self.box_top.addLayout(self.box_upper)
        self.box_top.addWidget(self.label_results)
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
        quizletDeckID = self.getQuizletDeckID()

        if quizletDeckID == None:
            return

        webbrowser.open(
            "https://quizlet.com/{}/flashcards".format(quizletDeckID))

    def onDiscussion(self):
        """
        Opens the audio fix discussion page in a browser
        """
        webbrowser.open("https://github.com/sviatoslav-lebediev/anki-quizlet-importer-extended/discussions/156")

    def getQuizletDeckID(self):
        # grab url input
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
        elif not bool(re.search(r'\d', quizletDeckID)):
            self.label_results.setText(
                "Oops! No deck ID found in path <i>{0}</i> :(".format(quizletDeckID))
            return
        else:  # get first set of digits from url path
            quizletDeckID = re.search(r"\d+", quizletDeckID).group(0)

        return quizletDeckID

    def onCode(self):
        html = self.value_incoming_html.toPlainText()
        quizletDeckID = self.getQuizletDeckID()

        if quizletDeckID == None:
            return

        # and aaawaaaay we go...
        self.label_results.setText("Connecting to Quizlet...")

        # build URL
        deck_url = "https://quizlet.com/{}/flashcards".format(quizletDeckID)

        # download the data!
        self.thread = QuizletDownloader(self, deck_url, quizletDeckID, html)
        self.thread.start()

        while not self.thread.isFinished():
            mw.app.processEvents()
            self.thread.wait(50)

        # error fetching data
        if self.thread.error:
            if self.thread.errorCode == 403:
                if self.thread.errorCaptcha:
                    self.label_results.setText(
                        "Sorry, it's behind a captcha. Try to disable VPN")
                else:
                    self.label_results.setText(
                        "Sorry, this is a private deck :(")
            elif self.thread.errorCode == 404:
                self.label_results.setText(
                    "Can't find a deck with the ID <i>{0}</i>".format(quizletDeckID))
            else:
                self.label_results.setText("Unknown Error")
                # errorMessage = json.loads(self.thread.errorMessage)
                # showText(json.dumps(errorMessage, indent=4))
                showText(self.thread.errorMessage)
        else:  # everything went through, let's roll!
            deck = self.thread.results
            # self.label_results.setText(("Importing deck {0} by {1}...".format(deck["title"], deck["created_by"])))
            self.label_results.setText(
                ("Importing deck {0}...".format(deck["title"])))
            self.createDeck(deck)
            # self.label_results.setText(("Success! Imported <b>{0}</b> ({1} cards by <i>{2}</i>)".format(deck["title"], deck["term_count"], deck["created_by"])))
            self.label_results.setText(
                ("Success! Imported <b>{0}</b> ({1} cards)".format(deck["title"], deck["term_count"])))

        # self.thread.terminate()
        self.thread = None

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
        model = addCustomModel(name, mw.col)

        # assign custom model to new deck
        mw.col.decks.select(deck["id"])
        mw.col.decks.save(deck)

        # assign new deck to custom model
        mw.col.models.setCurrent(model)
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
                    file_name = self.fileDownloader(item["imageUrl"])
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
            except urllib2.HTTPError as e:
                if fallback and not fallback_call and self.config.get('license'):
                    fallback_call = True
                    url = "https://quizlet-proxy.proto.click/quizlet-media?url={0}".format(urllib.parse.quote(url))
                    request_headers["x-api-key"] = self.config.get("license")
                    continue
                if skip_errors:
                    return None
                else:
                    debug(f"throwing exception {e.code}")
                    raise e


def download_media (url, file_name, headers):
    r = urllib2.urlopen(urllib2.Request(url, headers=headers))

    if r.getcode() == 200:
        with open(mw.col.media.dir() + "/" + file_name, 'wb') as f:
            f.write(r.read())
    return file_name

def parseTextItem(item):
    return getText(item["richText"], item["plainText"])


def mapItems(studiableItems, setIdToDiagramImage=None):
    result = []

    for studiableItem in studiableItems:
        image = None
        term_audio = None
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
                config = mw.addonManager.getConfig(__name__)
                cookies = {}

                if config["qlts"]:
                    cookies = {"qlts": config["qlts"]}
                elif config["cookies"]:
                    from http.cookies import SimpleCookie
                    C = SimpleCookie()
                    C.load(config["cookies"])
                    cookies = {key: morsel.value for key, morsel in C.items()}

                page_html = ''

                if self.html:
                    page_html = self.html
                else:
                    url = self.url if proxyRetry else 'https://quizlet-proxy.proto.click/quizlet-deck?url=' + \
                        urllib.parse.quote(self.url, safe='()*!\'')
                    r = requests.get(url, verify=False,
                                     headers=headers, cookies=cookies)
                    r.raise_for_status()
                    page_html = r.text

                regex = re.escape('window.Quizlet["setPasswordData"]')

                if re.search(regex, page_html):
                    if (proxyRetry):
                        proxyRetry = False
                        continue
                    else:
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
                    rawData = m.group(1).strip()
                    data = json.loads(json.loads(rawData))
                    studiableItems = data["studyModesCommon"]["studiableData"]["studiableItems"]
                    setIdToDiagramImage = data["studyModesCommon"]["studiableData"]["setIdToDiagramImage"]

                if not studiableItems:
                    raise Exception("Can't extract data")

                self.results = {}
                self.results['items'] = mapItems(
                    studiableItems, setIdToDiagramImage)

                title = os.path.basename(
                    self.url.strip()) or "Quizlet Flashcards"
                m = re.search(r'<title>(.+?)</title>', page_html)

                if m:
                    title = m.group(1)
                    title = re.sub(r' \| Quizlet$', '', title)
                    title = re.sub(r'^Flashcards ', '', title)
                    title = re.sub(r'\s+', ' ', title)
                    title = title.strip()

                self.results['title'] = title

            except requests.HTTPError as e:
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
                    proxyRetry = False
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
action = QAction("Import from Quizlet", mw)
action.triggered.connect(runQuizletPlugin)
mw.form.menuTools.addAction(action)
