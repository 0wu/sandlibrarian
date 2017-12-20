from flask import Flask, request, make_response
import os
import json
import time

from mendeley import Mendeley
import yaml
import requests

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
    # Parse the request payload
    message_action = json.loads(request.form["payload"])
    user_id = message_action["user"]["id"]
    print(message_action)

    if message_action["type"] == "interactive_message" and message_action['actions'][0]['name'] == 'token':
        mendeley_token['message_ts'] = message_action["message_ts"]
        print(len(auth.get_login_url()))
        open_dialog = slack_client.api_call(
            "dialog.open",
            trigger_id=message_action["trigger_id"],
            dialog={
                "title": "Get token from here",
                "submit_label": "Submit",
                "callback_id": config['user'] + "token",
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

        print(open_dialog)


    elif message_action["type"] == "interactive_message" and message_action['actions'][0]['name'] != 'token':
        # Add the message_ts to the user's order info
        PDF_TAGS[user_id]["message_ts"] = message_action["message_ts"]

        # Show the ordering dialog to the user
        open_dialog = slack_client.api_call(
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

        print(open_dialog)

        # Update the message to show that we're in the process of taking their order
        slack_client.api_call(
            "chat.update",
            channel=PDF_TAGS[user_id]["order_channel"],
            ts=message_action["message_ts"],
            text=":pencil: Adding tags...",
            attachments=[]
        )

    elif message_action["type"] == "dialog_submission" and 'inserted_token' in message_action['submission'].keys():
        token = message_action['submission']['inserted_token']
        print(token)
        mendeley_token['session'] = auth.authenticate(token)
        # mendeley_session = auth.authenticate(token)
        # Update the message to show that we're in the process of taking their order
        slack_client.api_call(
            "chat.update",
            channel=config['user'],
            ts=mendeley_token["message_ts"],
            text=":white_check_mark: PDF tagged!",
            attachments=[]
        )

    elif message_action["type"] == "dialog_submission" and 'inserted_token' not in message_action['submission'].keys():
        tag_order = PDF_TAGS[user_id]
        doc_url = tag_order["doc_url"]

        tags = message_action['submission']['tags'].split(",")
        # Update the message to show that we're in the process of taking their order
        slack_client.api_call(
            "chat.update",
            channel=PDF_TAGS[user_id]["order_channel"],
            ts=tag_order["message_ts"],
            text=":white_check_mark: PDF uploaded and tagged!",
            attachments=[]
        )
        req_down = requests.get(doc_url,
                                headers={"Authorization": "Bearer %s" % os.environ.get('SLACK_BOT_TOKEN')})
        # print(req_down.content)
        doc = mendeley_token['session'].documents.create_pdf_from_requests(req_down.content, tag_order['doc_name'])
        updated_doc = doc.update(tags=tags)


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
