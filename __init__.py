#-------------------------------------------------------------------------------
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
#               - Rolph's plugin functionality was broken, so...
#               - removed search tables and associated functions to KISS
#               - reused the original API key, dunno if that's OK
#               - replaced with just one box, for a quizlet URL
#               - added basic error handling for dummies
#
#               Update 04/09/2017
#               - modified to now take a full Quizlet url for ease of use
#               - provide feedback if trying to download a private deck
#               - return RFC 2616 response codes when error handling
#               - don't make a new card type every time a new deck imported
#               - better code documentation so people can modify it
#
#               Update 01/31/2018
#               - get original quality images instead of mobile version
#
# Changlog (by kelciour):
#               Update 09/12/2018
#               - updated to Anki 2.1
#
#               Update 04/02/2020
#               - download a set without API key since it's no longer working
#
#               Update 19/02/2020
#               - download private or password-protected sets using cookies
#
#               Update 25/02/2020
#               - make it work again by adding the User-Agent header
#
#               Update 14/04/2020
#               - try to get title from HTML a bit differently
#
#               Update 29/04/2020
#               - suggest to disable VPN if a set is blocked by a captcha
#
#               Update 04/05/2020
#               - remove Flashcards from the name of the deck
#               - rename and create a new Basic Quizlet note type if some fields doesn't exist
#
#               Update 17/05/2020
#               - use setPageData and assistantModeData as a possible source for flashcards data
#
#               Update 22/07/2020
#               - fix for Anki 2.1.28
#
#               Update 30/08/2020
#               - add Return shortcut
#
#               Update 31/08/2020
#               - add rich text formatting
#
#               Update 03/09/2020
#               - make it working again after Quizlet update

#               Update 04/09/2020
#               - move the add-on to GitHub
#               Update 17/10/2020
#     
#-------------------------------------------------------------------------------
#!/usr/bin/env python

__window = None

import sys, math, time, urllib.parse, json, re, os

# Anki
from aqt import mw
from aqt.qt import *
from aqt.utils import showText
from anki.utils import checksum

import requests
import shutil

requests.packages.urllib3.disable_warnings()

headers = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.102 Safari/537.36"
}

rich_text_css = """
:root {
  --yellow_light_background: #fff4e5;
  --blue_light_background: #cde7fa;
  --pink_light_background: #fde8ff;
}

.nightMode {
  --yellow_light_background: #8c7620;
  --blue_light_background: #295f87;
  --pink_light_background: #7d537f;
}

.bgY {
  background-color: var(--yellow_light_background);
}

.bgB {
  background-color: var(--blue_light_background);
}

.bgP {
  background-color: var(--pink_light_background);
}
"""

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

class QuizletWindow(QWidget):

    # used to access Quizlet API
    __APIKEY = "ke9tZw8YM6"

    # main window of Quizlet plugin
    def __init__(self):
        super(QuizletWindow, self).__init__()

        self.results = None
        self.thread = None
        self.closed = False

        self.cookies = self.getCookies()

        self.initGUI()

    # create GUI skeleton
    def initGUI(self):

        self.box_top = QVBoxLayout()
        self.box_upper = QHBoxLayout()

        # left side
        self.box_left = QVBoxLayout()

        # quizlet url field
        self.box_name = QHBoxLayout()
        self.label_url = QLabel("Quizlet URL:")
        self.text_url = QLineEdit("",self)
        self.text_url.setMinimumWidth(300)

        self.box_name.addWidget(self.label_url)
        self.box_name.addWidget(self.text_url)
        # parentDeck field

        self.box_parent = QHBoxLayout()
        self.label_parentDeck = QLabel("Parent deck name")
        self.parentDeck = QLineEdit ("",self)
        self.parentDeck.setMinimumWidth(300)

        self.box_parent.addWidget(self.label_parentDeck)
        self.box_parent.addWidget(self.parentDeck)

        # add layouts to left

        self.box_left.addLayout(self.box_name)
        self.box_left.addLayout(self.box_parent)
        # right side
        self.box_right = QVBoxLayout()

        # code (import set) button
        self.box_code = QHBoxLayout()
        self.button_code = QPushButton("Import Deck", self)
        self.button_code.setShortcut(QKeySequence("Return"))
        self.box_code.addStretch(1)
        self.box_code.addWidget(self.button_code)
        self.button_code.clicked.connect(self.onCode)

        # add layouts to right
        self.box_right.addLayout(self.box_code)

        # add left and right layouts to upper
        self.box_upper.addLayout(self.box_left)
        self.box_upper.addSpacing(20)
        self.box_upper.addLayout(self.box_right)

        # results label
        self.label_results = QLabel("This importer has three use cases: 1. single url; 2. multiple urls on multiple lines and 3. folder.\n Parent deck name can be cutomized. If not provided, it will either use the folder name \n(if a folder url is provided) or save the deck as a first-level deck.\n\n Single url example: https://quizlet.com/515858716/japanese-shops-fruit-flash-cards/")

        # add all widgets to top layout
        self.box_top.addLayout(self.box_upper)
        self.box_top.addSpacing(10)
        self.box_top.addWidget(self.label_results)
        self.box_top.addStretch(1)
        self.setLayout(self.box_top)

        # go, baby go!
        self.setMinimumWidth(500)
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
        self.setWindowTitle("Improved Quizlet to Anki Importer")
        self.resize(self.minimumSizeHint())
        self.show()

    def getCookies(self):
        config = mw.addonManager.getConfig(__name__)

        cookies = {}
        if config["qlts"]:
            cookies = { "qlts": config["qlts"] }
        elif config["cookies"]:
            from http.cookies import SimpleCookie
            C = SimpleCookie()
            C.load(config["cookies"])
            cookies = { key: morsel.value for key, morsel in C.items() }
        return cookies

    def onCode(self):
        parentDeck = self.parentDeck.text()
        # grab url input
        report = {'error': [], 'success': []}
        urls = self.text_url.text().splitlines()
        self.label_results.setText(("There are <b>{0}</b> urls in total. Starting".format(len(urls))))
        self.sleep(0.5)
        for url in urls:
            if not url:
                continue

            # voodoo needed for some error handling
            if urllib.parse.urlparse(url).scheme:
                urlDomain = urllib.parse.urlparse(url).netloc
                urlPath = urllib.parse.urlparse(url).path
            else:
                urlDomain = urllib.parse.urlparse("https://"+url).netloc
                urlPath = urllib.parse.urlparse("https://"+url).path

            # validate quizlet URL
            if url == "":
                self.label_results.setText("Oops! You forgot the deck URL :(")
                return
            elif not "quizlet.com" in urlDomain:
                self.label_results.setText("Oops! That's not a Quizlet URL :(")
                return
            self.button_code.setEnabled(False)

            if "/folders/" not in url:
                self.downloadSet(url, parentDeck)
                self.sleep(1.5)
            elif "/folders/" in url :
                r = requests.get(url, verify=False, headers=headers, cookies=self.cookies)
                r.raise_for_status()

                regex = re.escape('window.Quizlet["dashboardData"] = ')
                regex += r'(.+?)'
                regex += re.escape('; QLoad("Quizlet.dashboardData");')

                m = re.search(regex, r.text)

                data = m.group(1).strip()
                results = json.loads(data)

                assert len(results["models"]["folder"]) == 1

                quizletFolder = results["models"]["folder"][0]
                setMap = { s["id"]:s for s in results["models"]["set"] }
                for folderSet in results["models"]["folderSet"]:
                    if self.closed:
                        return
                    quizletSet = setMap[folderSet["setId"]]
                    if parentDeck == "":
                        self.downloadSet(quizletSet["_webUrl"], quizletFolder["name"])
                    else:
                        self.downloadSet(quizletSet["_webUrl"], parentDeck)
                    self.sleep(1.5)

            self.button_code.setEnabled(True)

    def closeEvent(self, evt):
        self.closed = True
        evt.accept()

    def sleep(self, seconds):
        start = time.time()
        while time.time() - start < seconds:
            time.sleep(0.01)
            QApplication.instance().processEvents()

    def downloadSet(self, urlPath, parentDeck=""):
        # validate and set Quizlet deck ID
        quizletDeckID = urlPath.strip("/")
        if quizletDeckID == "":
            self.label_results.setText("Oops! Please use the full deck URL :(")
            return
        elif not bool(re.search(r'\d', quizletDeckID)):
            self.label_results.setText("Oops! No deck ID found in path <i>{0}</i> :(".format(quizletDeckID))
            return
        else: # get first set of digits from url path
            quizletDeckID = re.search(r"\d+", quizletDeckID).group(0)

        # and aaawaaaay we go...
        self.label_results.setText("Connecting to Quizlet...")

        # build URL
        # deck_url = ("https://api.quizlet.com/2.0/sets/{0}".format(quizletDeckID))
        # deck_url += ("?client_id={0}".format(QuizletWindow.__APIKEY))
        # deck_url = "https://quizlet.com/{}/flashcards".format(quizletDeckID)
        deck_url = urlPath

        # stop previous thread first
        # if self.thread is not None:
        #     self.thread.terminate()

        # download the data!
        self.thread = QuizletDownloader(self, deck_url)
        self.thread.start()

        while not self.thread.isFinished():
            mw.app.processEvents()
            self.thread.wait(50)

        # error fetching data
        if self.thread.error:
            if self.thread.errorCode == 403:
                if self.thread.errorCaptcha:
                    self.label_results.setText("Sorry, it's behind a captcha. Try to disable VPN")
                else:
                    self.label_results.setText("Sorry, this is a private deck :(")
            elif self.thread.errorCode == 404:
                self.label_results.setText("Can't find a deck with the ID <i>{0}</i>".format(quizletDeckID))
            else:
                self.label_results.setText("Unknown Error")
                # errorMessage = json.loads(self.thread.errorMessage)
                # showText(json.dumps(errorMessage, indent=4))
                showText(self.thread.errorMessage)
        else: # everything went through, let's roll!
            deck = self.thread.results
            # self.label_results.setText(("Importing deck {0} by {1}...".format(deck["title"], deck["created_by"])))
            self.label_results.setText(("Importing deck {0}...".format(deck["title"])))
            self.createDeck(deck, parentDeck)
            # self.label_results.setText(("Success! Imported <b>{0}</b> ({1} cards by <i>{2}</i>)".format(deck["title"], deck["term_count"], deck["created_by"])))
            self.label_results.setText(("Success! Imported <b>{0}</b> ({1} cards)".format(deck["title"], deck["term_count"])))

        # self.thread.terminate()
        self.thread = None

    def createDeck(self, result, parentDeck=""):
        config = mw.addonManager.getConfig(__name__)

        if config["rich_text_formatting"] and not os.path.exists("_quizlet.css"):
            with open("_quizlet.css", "w") as f:
                f.write(rich_text_css.lstrip())

        # create new deck and custom model
        if "set" in result:
            name = result['set']['title']
        elif "studyable" in result:
            name = result['studyable']['title']
        else:
            name = result['title']

        if parentDeck:
            name = "{}::{}".format(parentDeck, name)

        if "termIdToTermsMap" in result:
            terms = []
            for c in sorted(result['termIdToTermsMap'].values(), key=lambda v: v["rank"]):
                terms.append({
                    'word': c['word'],
                    'definition': c['definition'],
                    '_imageUrl': c["_imageUrl"] or '',
                    'wordRichText': c.get('wordRichText', ''),
                    'definitionRichText': c.get('definitionRichText', ''),
                })
        elif "studiableData" in result:
            terms = {}
            data = result["studiableData"]
            for d in data["studiableItems"]:
                terms[d["id"]] = {}
            smc = {}
            for d in data["studiableMediaConnections"]:
                id_ = d["connectionModelId"]
                if id_ not in smc:
                    smc[id_] = {}
                # "plainText", "languageCode", "ttsUrl", "ttsSlowUrl", "richText"
                for k, v in d.get("text", {}).items():
                    smc[id_][k] = v
                if "image" in d:
                    smc[id_]["_imageUrl"] = d["image"]["url"]
            for d in data["studiableCardSides"]:
                id_ = d["studiableItemId"]
                terms[id_][d["label"]] = smc[d["id"]].get("plainText", "")
                terms[id_]["{}RichText".format(d["label"])] = smc[d["id"]].get("richText", "")
                terms[id_]["_imageUrl"] = smc[d["id"]].get("_imageUrl", "")
            terms = terms.values()
        else:
            terms = result['terms']

        result['term_count'] = len(terms)

        deck = mw.col.decks.get(mw.col.decks.id(name))
        model = addCustomModel(name, mw.col)

        if config["rich_text_formatting"] and ".bgY" not in model["css"]:
            model["css"] += rich_text_css

        # assign custom model to new deck
        mw.col.decks.select(deck["id"])
        mw.col.decks.save(deck)

        # assign new deck to custom model
        mw.col.models.setCurrent(model)
        model["did"] = deck["id"]
        mw.col.models.save(model)

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
                            attrs = " ".join(['{}="{}"'.format(k, v) for k, v in m['attrs'].items()])
                            text = '<span {}>{}</span>'.format(attrs, text)
                return text
            text = ''.join([getText(c) if c else '<br>' for c in d.get('content', [''])])
            if d['type'] == 'paragraph':
                text = '<div>{}</div>'.format(text)
            return text

        def ankify(text):
            text = text.replace('\n','<br>')
            text = re.sub(r'\*(.+?)\*', r'<b>\1</b>', text)
            return text

        for term in terms:
            note = mw.col.newNote()
            note["Front"] = ankify(term['word'])
            note["Back"] = ankify(term['definition'])
            if config["rich_text_formatting"]:
                note["Front"] = getText(term['wordRichText'], note["Front"])
                note["Back"] = getText(term['definitionRichText'], note["Back"])
            if "photo" in term and term["photo"]:
                photo_urls = {
                  "1": "https://farm{1}.staticflickr.com/{2}/{3}_{4}.jpg",
                  "2": "https://o.quizlet.com/i/{1}.jpg",
                  "3": "https://o.quizlet.com/{1}.{2}"
                }
                img_tkns = term["photo"].split(',')
                img_type = img_tkns[0]
                term["_imageUrl"] = photo_urls[img_type].format(*img_tkns)
            if '_imageUrl' in term and term["_imageUrl"]:
                # file_name = self.fileDownloader(term["image"]["url"])
                file_name = self.fileDownloader(term["_imageUrl"])
                if note["Back"]:
                    note["Back"] += "<div><br></div>"
                note["Back"] += '<div><img src="{0}"></div>'.format(file_name)
                mw.app.processEvents()
            if config["rich_text_formatting"]:
                note["Front"] = '<link rel="stylesheet" href="_quizlet.css">' + note["Front"]
            mw.col.addNote(note)
        mw.col.reset()
        mw.reset()

    # download the images
    def fileDownloader(self, url):
        url = url.replace('_m', '')
        file_name = "quizlet-" + url.split('/')[-1]
        # get original, non-mobile version of images
        r = requests.get(url, stream=True, verify=False, headers=headers)
        if r.status_code == 200:
            with open(file_name, 'wb') as f:
                r.raw.decode_content = True
                shutil.copyfileobj(r.raw, f)
        return file_name

class QuizletDownloader(QThread):

    # thread that downloads results from the Quizlet API
    def __init__(self, window, url):
        super(QuizletDownloader, self).__init__()
        self.window = window

        self.url = url
        self.results = None

        self.error = False
        self.errorCode = None
        self.errorCaptcha = False
        self.errorReason = None
        self.errorMessage = None

    def run(self):
        r = None
        try:
            r = requests.get(self.url, verify=False, headers=headers, cookies=self.window.cookies)
            r.raise_for_status()

            regex = re.escape('window.Quizlet["setPasswordData"]')

            if re.search(regex, r.text):
                self.error = True
                self.errorCode = 403
                return

            regex = re.escape('window.Quizlet["setPageData"] = ')
            regex += r'(.+?)'
            regex += re.escape('; QLoad("Quizlet.setPageData");')
            m = re.search(regex, r.text)

            if not m:
                regex = re.escape('window.Quizlet["assistantModeData"] = ')
                regex += r'(.+?)'
                regex += re.escape('; QLoad("Quizlet.assistantModeData");')
                m = re.search(regex, r.text)

            if not m:
                regex = re.escape('window.Quizlet["cardsModeData"] = ')
                regex += r'(.+?)'
                regex += re.escape('; QLoad("Quizlet.cardsModeData");')
                m = re.search(regex, r.text)

            data = m.group(1).strip()
            self.results = json.loads(data)

            title = os.path.basename(self.url.strip()) or "Quizlet Flashcards"
            m = re.search(r'<title>(.+?)</title>', r.text)
            if m:
                title = m.group(1)
                title = re.sub(r' \| Quizlet$', '', title)
                title = re.sub(r'^Flashcards ', '', title)
                title = re.sub(r'\s+', ' ', title)
                title = title.strip()
            self.results['title'] = title
        except requests.HTTPError as e:
            self.error = True
            self.errorCode = e.response.status_code
            self.errorMessage = e.response.text
            if "CF-Chl-Bypass" in e.response.headers:
                self.errorCaptcha = True
        except ValueError as e:
            self.error = True
            self.errorMessage = "Invalid json: {0}".format(e)
        except Exception as e:
            self.error = True
            self.errorMessage = "{}\n-----------------\n{}".format(e, r.text if r else "")
        # yep, we got it

# plugin was called from Anki
def runQuizletPlugin():
    global __window
    __window = QuizletWindow()

# create menu item in Anki
action = QAction("Import from Quizlet", mw)
action.triggered.connect(runQuizletPlugin)
mw.form.menuTools.addAction(action)