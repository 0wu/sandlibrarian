from flask import Flask, request, make_response
import os
import json
import time

from mendeley import Mendeley
import yaml
import requests

from threading import Thread
from slackclient import SlackClient

# Your app's Slack bot user token
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
# SLACK_VERIFICATION_TOKEN = os.environ["SLACK_VERIFICATION_TOKEN"]

# Slack client for Web API requests
slack_client = SlackClient(SLACK_BOT_TOKEN)
PDF_TAGS = {}
mendeley_token = {}
processed_tokens = []
# Flask webserver for incoming traffic from Slack
app = Flask(__name__)

with open('config.yml') as f:
    config = yaml.load(f)

men = Mendeley(config['clientId'], config['clientSecret'],
               'http://localhost:5000/oauth')

auth = men.start_authorization_code_flow()
# print("please go to:", auth.get_login_url())
response = slack_client.api_call(
  "chat.postMessage",
  as_user=True,
  channel=config['user'],
  # ts=form_json["message_ts"],
  text="%s" % auth.get_login_url(),
  attachments=[]
)
time.sleep(20)
token_dm = slack_client.api_call(
  "chat.postMessage",
  as_user=True,
  channel=config['user'],
  text="I am Librarian ::robot_face::, please give me a token",
  attachments=[{
    "text": "",
    "callback_id": config['user'] + "token",
    "color": "#3AA3E3",
    "attachment_type": "default",
    "actions": [{
      "name": "token",
      "text": "insert a token please",
      "type": "button",
      "value": "token"
    }]
  }]
)


def process_data(doc_url, doc_name, tags):
    """This function handles the pdf upload to Mendeley.

    Parameters
    ----------
    doc_url: str
        slack url where the pdf can be found
    doc_name: str
        name of the file to be uploaded to Mendeley
    tags: list
        list of strings to be added as tags to the pdf

    We use a separate function here for the pdf upload as the slack
    dialog needs an HTTP 200 response within 3 seconds. This function
    gets called within a thread started by the interactive slack dialog for
    uploading and tagging. We first need to download the pdf from slack
    and then use the mendeley api to create a new document from a
    request response.
    """
    req_down = requests.get(doc_url,
                            headers={"Authorization": "Bearer %s"
                                     % os.environ.get('SLACK_BOT_TOKEN')})
    doc = (mendeley_token['session'].documents
           .create_pdf_from_requests(req_down.content, doc_name))
    _ = doc.update(tags=tags)


def _event_handler(event_type, slack_event, mendeley_session):
    """
    A helper function that routes events from Slack to our Bot
    by event type and subtype.

    Parameters
    ----------
    event_type : str
        type of event recieved from Slack
    slack_event : dict
        JSON response from a Slack reaction event

    Returns
    ----------
    obj
        Response object with 200 - ok or 500 - No Event Handler error

    """

    # ================ Team Join Events =============== #
    # When the user first joins a team, the type of event will be team_join
    # print(event_type)
    print("----------------", slack_event, "-------------")
    if event_type == 'file_shared':
        if slack_event['event']['file']['id'] in processed_tokens:
            return make_response("Welcome Message Sent", 200,)
        processed_tokens.append(slack_event['event']['file']['id'])
        webhook_url = "https://slack.com/api/files.info"
        slack_data = {'token': os.environ.get('SLACK_BOT_TOKEN'),
                      'file': slack_event["event"]['file_id']}
        req = requests.post(webhook_url, data=slack_data,
                            headers={'Content-Type':
                                     'application/x-www-form-urlencoded'})

        file_info = json.loads(req.content)
        print(file_info)
        if file_info['ok'] and file_info['file']['filetype'] == 'pdf':

            order_dm = slack_client.api_call(
              "chat.postMessage",
              as_user=True,
              channel=slack_event["event"]['user_id'],
              text="I am Librarian ::robot_face::, and I\'m here to help you tag the pdf you just uploaded",
              attachments=[{
                "text": "",
                "callback_id": slack_event["event"]['user_id'] + "pdf_tag_form",
                "color": "#3AA3E3",
                "attachment_type": "default",
                "actions": [{
                  "name": "pdf_tag",
                  "text": "Upload PDF to Mendeley and add tags",
                  "type": "button",
                  "value": "pdf_tag"
                }]
              }]
            )

            # req_down = requests.get(file_info['file']['url_private'],
            #                         headers={"Authorization": "Bearer %s" % os.environ.get('SLACK_BOT_TOKEN')})
            # # print(req_down.content)
            # doc = mendeley_session.documents.create_pdf_from_requests(req_down.content, file_info['file']['name'])
            # print(doc)
            # Create a new order for this user in the PDF_TAGS dictionary
            PDF_TAGS[slack_event["event"]['user_id']] = {
                "order_channel": order_dm["channel"],
                "message_ts": "",
                "order": {},
                "doc_url": file_info['file']['url_private'],
                'doc_name': file_info['file']['name']
            }
            # updated_doc = doc.update(tags=["sandtable, yeah"])
            # print(updated_doc)
        return make_response("Welcome Message Sent", 200,)

    # ============= Event Type Not Found! ============= #
    # If the event_type does not have a handler
    message = "You have not added an event handler for the %s" % event_type
    # Return a helpful error message
    return make_response(message, 200, {"X-Slack-No-Retry": 1})


@app.route("/slack/message_actions", methods=["POST"])
def message_actions():
    """This function receives and message actions and processess it.

    This function has to return a HTTP 200 response within 3 seconds.
    It handles all the processing of users responses to interactive elements.
    """
    # Parse the request payload
    message_action = json.loads(request.form["payload"])
    # check the verification token
    if message_action['token'] == SLACK_VERIFICATION_TOKEN:
        user_id = message_action["user"]["id"]

        # If it is an interactive message swith the token action open a dialog
        # for the user to enter the token url
        if (message_action["type"] == "interactive_message" and
                message_action['actions'][0]['name'] == 'token'):
            mendeley_token['message_ts'] = message_action["message_ts"]
            _ = slack_client.api_call(
                "dialog.open",
                trigger_id=message_action["trigger_id"],
                dialog={
                    "title": "Get token from here",
                    "submit_label": "Submit",
                    "callback_id": SLACK_MENDELEY_LOGIN + "token",
                    "elements": [
                        {
                            "label": "token",
                            "type": "text",
                            "name": "inserted_token",
                            "value": "",
                        }
                    ]
                }
            )
        # if it is a interactive message without a token assume its a tagging
        # process.
        elif (message_action["type"] == "interactive_message" and
              message_action['actions'][0]['name'] != 'token'):
            # Open a dialog to the user to let him add tags to the pdf
            PDF_TAGS[user_id]["message_ts"] = message_action["message_ts"]

            slack_client.api_call(
                "dialog.open",
                trigger_id=message_action["trigger_id"],
                dialog={
                    "title": "Tag the pdf",
                    "submit_label": "Submit",
                    "callback_id": user_id + "pdf_tag_form",
                    "elements": [
                        {
                            "label": "add tags",
                            "type": "textarea",
                            "name": "tags",
                            "placeholder": "insert tags as simple comma separated words (e.g. byroniser, agent based model, test)",
                        }
                    ]
                }
            )

            # Update the user that things are happening
            slack_client.api_call(
              "chat.postEphemeral",
              as_user=True,
              channel=PDF_TAGS[user_id]["order_channel"],
              user=user_id,
              text="Tagging the pdf",
              attachments=[]
            )

        # if it is a submission fo a dialog with a token finish mendelen auth
        # process. Save the session in the mendeley dict.
        elif (message_action["type"] == "dialog_submission" and
              'inserted_token' in message_action['submission'].keys()):
            mendeley_token['session'] = auth.authenticate(
                message_action['submission']['inserted_token'])
            slack_client.api_call(
                "chat.update",
                channel=SLACK_MENDELEY_LOGIN,
                ts=mendeley_token["message_ts"],
                text=":white_check_mark: PDF tagged!",
                attachments=[]
            )
        # if the submission is not a token then it will be tags so
        # read in the tags start a thread with uploading and tagging
        # and return a 200 HTTP response
        elif (message_action["type"] == "dialog_submission" and
              'inserted_token' not in message_action['submission'].keys()):
            tag_order = PDF_TAGS[user_id]
            doc_url = tag_order["doc_url"]
            tags = message_action['submission']['tags'].split(",")
            # Update the user that the pdf was tagged and is being uploaded
            slack_client.api_call(
              "chat.postEphemeral",
              as_user=True,
              channel=PDF_TAGS[user_id]["order_channel"],
              user=user_id,
              text="Tagging complete uploading to mendeley",
              attachments=[]
            )
            t = Thread(target=process_data,
                       args=(doc_url, tag_order['doc_name'], tags))
            t.start()

        return make_response("", 200)


@app.route("/listening", methods=["GET", "POST"])
def hears():
    """
    This route listens for incoming events from Slack and uses the event
    handler helper function to route events to our Bot.
    """
    slack_event = json.loads(request.data)
    if 'session' in mendeley_token.keys():
        mendeley_session = mendeley_token['session']
    else:
        mendeley_session = None

    # ============= Slack URL Verification ============ #
    # In order to verify the url of our endpoint, Slack will send a challenge
    # token in a request and check for this token in the response our endpoint
    # sends back.
    #       For more info: https://api.slack.com/events/url_verification
    if "challenge" in slack_event:
        return make_response(slack_event["challenge"], 200, {"content_type":
                                                             "application/json"
                                                             })

    # ====== Process Incoming Events from Slack ======= #
    # If the incoming request is an Event we've subcribed to
    if "event" in slack_event:
        event_type = slack_event["event"]["type"]
        # Then handle the event by event_type and have your bot respond
        return _event_handler(event_type, slack_event, mendeley_session)
    # If our bot hears things that are not events we've subscribed to,
    # send a quirky but helpful error response
    return make_response("[NO EVENT IN SLACK REQUEST] These are not the droids\
                         you're looking for.", 404, {"X-Slack-No-Retry": 1})


if __name__ == "__main__":
    app.run()
