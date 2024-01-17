# Quizlet importer Extended

Upgraded version of the quizlet importer which imports audio files.

<a href="https://www.buymeacoffee.com/moro.programmer" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: auto !important;width: 140px !important;" ></a>

Instead of creating Front and Back items this version creates these fields

    * FrontText
    * FrontAudio
    * BackText
    * BackAudio
    * Image
    * Add Reverse

Note type name is `Basic Quizlet Extended`;

Supports start and stop phrases. It allows you to download a part of the quizlet collection.
![image](https://user-images.githubusercontent.com/19693768/198877987-63beb40b-20dd-4ee1-94fd-c7e7c33e9297.png)

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
