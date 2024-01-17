# Quizlet importer Extended

Upgraded version of the quizlet importer which imports audio files.

<a href="https://www.buymeacoffee.com/moro.programmer" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: auto !important;width: 140px !important;" ></a>

[FAQ](https://github.com/sviatoslav-lebediev/anki-quizlet-importer-extended/wiki/FAQ)

Instead of creating Front and Back items this version creates these fields

    * FrontText
    * FrontAudio
    * BackText
    * BackAudio
    * Image
    * Add Reverse

Note type name is `Basic Quizlet Extended`;

Supports start and stop phrases. It allows you to download a part of the quizlet collection.

![image](https://github.com/sviatoslav-lebediev/anki-quizlet-importer-extended/assets/19693768/2b08ec5b-44db-4a71-9c45-488ced6f535c)

The skip errors checkbox allows to skip media download errors.

### This addon creates two types of cards: Normal and Reverse

**Normal Template has**:

* Front

    ```html
    {{FrontText}}
    <br><br>
    {{FrontAudio}}
    ```

* Back
    ```html
    {{FrontText}}
    <hr id=answer>
    {{BackText}}
    <br><br>
    {{Image}}
    <br><br>
    {{BackAudio}}
    ```

**Reverse Template is**:

* Front
    ```html
    {{#Add Reverse}}
    {{BackText}}
    <br><br>
    {{BackAudio}}
    {{/Add Reverse}}
    ```

* Back
    ```html
    {{BackText}}
    <hr id=answer>
    {{FrontText}}
    <br><br>
    {{FrontAudio}}
    {{Image}}
    ```

### Fields formats

* FrontAudio - `[sound:"quizlet-CARD_ID-front.mp3"]`
* BackAudio - `[sound:"quizlet-CARD_ID-back.mp3"]`
* Image - `<img src="file_name">`

## Repo Activity

![Repo Activity](https://repobeats.axiom.co/api/embed/94e61d46859061470cdf238cbad04e80bcc57300.svg "Repobeats analytics image")
