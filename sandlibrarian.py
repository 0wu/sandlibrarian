from flask import Flask, request, make_response
import os
import json
import time
import requests

from mendeley import Mendeley
from threading import Thread
from slackclient import SlackClient

# Your app's Slack bot user token
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_VERIFICATION_TOKEN = os.environ["SLACK_VERIFICATION_TOKEN"]
MENDELEY_CLIENTID = os.environ["MENDELEY_CLIENTID"]
MENDELEY_CLIENTSECRET = os.environ["MENDELEY_CLIENTSECRET"]
SLACK_MENDELEY_LOGIN = os.environ["SLACK_MENDELEY_USER"]
MENDELEY_REDIRECT = os.environ["MENDELEY_REDIRECT"]

# Slack client for Web API requests
slack_client = SlackClient(SLACK_BOT_TOKEN)
# This will keep track of which pdfs to tag
PDF_TAGS = {}
# this will be used for the mendeley session
mendeley_token = {}
# this will keep track of which pdfs have been processed to avoid double posts
processed_tokens = []
# Flask webserver for incoming traffic from Slack
app = Flask(__name__)
# Start mendeley client and Auth workflow
men = Mendeley(MENDELEY_CLIENTID, MENDELEY_CLIENTSECRET,
               MENDELEY_REDIRECT)
auth = men.start_authorization_code_flow()
# message user to authorise mendeley api
response = slack_client.api_call(
  "chat.postMessage",
  as_user=True,
  channel=SLACK_MENDELEY_LOGIN,
  text="Please go to this URL and login with your Mendeley account. After the successful login you will get to an error page. Copy the url of this error page and past it into the interactive dialog created by this bot in ~20 seconds: %s" % auth.get_login_url(),
  attachments=[]
)
# give the user 20 seconds to retrieve the token (3 second timeout on the
# interactive message)
time.sleep(20)
token_dm = slack_client.api_call(
  "chat.postMessage",
  as_user=True,
  channel=SLACK_MENDELEY_LOGIN,
  text="I am Librarian ::robot_face::, please give me a token",
  attachments=[{
    "text": "",
    "callback_id": SLACK_MENDELEY_LOGIN + "token",
    "color": "#3AA3E3",
    "attachment_type": "default",
    "actions": [{
      "name": "token",
      "text": "insert the url please",
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

    # ================ file share events =============== #
    # When the user uploads a pdf, the type of event will be file_shared
    if event_type == 'file_shared':
        # check if the file id has been processed already
        # for some reasons sometimes we get two/three events.
        if slack_event['event']['file']['id'] in processed_tokens:
            return make_response("Welcome Message Sent", 200,)
        # add file id to processed file list
        processed_tokens.append(slack_event['event']['file']['id'])
        # get the info of the file that was just uploaded
        webhook_url = "https://slack.com/api/files.info"
        slack_data = {'token': os.environ.get('SLACK_BOT_TOKEN'),
                      'file': slack_event["event"]['file_id']}
        req = requests.post(webhook_url, data=slack_data,
                            headers={'Content-Type':
                                     'application/x-www-form-urlencoded'})

        file_info = json.loads(req.content)
        # check if the file has been uploaded correctly and if it's type is pdf
        if file_info['ok'] and file_info['file']['filetype'] == 'pdf':
            slack_data_user = {'token': os.environ.get('SLACK_BOT_TOKEN'),
                               'user': file_info['file']["user"]}
            req_user = requests.get('https://slack.com/api/users.info',
                                    params=slack_data_user)
            t = json.loads(req_user.content)
            user_name = t['user']['name']
            # inform user that he can upload and tag the file he just added
            # do this as ephemeral message to not spam all users
            _ = slack_client.api_call(
              "chat.postEphemeral",
              as_user=True,
              channel=file_info['file']["channels"][0],
              user=file_info['file']["user"],
              text="I am Librarian ::robot_face::, and I\'m here to help you tag the pdf you just uploaded. This message will be gone next time you open slack",
              attachments=[{
                "text": "",
                "callback_id": (slack_event["event"]['user_id'] +
                                "pdf_tag_form"),
                "color": "#3AA3E3",
                "attachment_type": "default",
                "actions": [{
                  "name": "pdf_tag",
                  "text": "add tags and upload",
                  "type": "button",
                  "value": "pdf_tag"
                }]
              }]
            )
            # add some info to the pdf tag dict so that it can be used
            # by the endpoint that deals with the responses from slack
            PDF_TAGS[slack_event["event"]['user_id']] = {
                "order_channel": file_info['file']["channels"][0],
                "message_ts": "",
                "doc_url": file_info['file']['url_private'],
                'doc_name': file_info['file']['name'],
                'default_tags': ["sandtable",
                                 time.strftime('%Y%m%d', time.localtime(file_info['file']["timestamp"])),
                                 file_info['file']["channels"][0],
                                 user_name]
            }
        return make_response("Welcome Message Sent", 200,)

    # ============= Event Type Not Found! ============= #
    # If the event_type does not have a handler
    message = "You have not added an event handler for the %s" % event_type
    # Return a helpful error message
    return make_response(message, 200, {"X-Slack-No-Retry": 1})


@app.route("/ping", methods=['get'])
def ping():
    return make_response("pong", 200)

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
            tags = (tag_order['default_tags'] +
                    message_action['submission']['tags'].split(","))
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

    # ============ Slack Token Verification =========== #
    # We can verify the request is coming from Slack by checking that the
    # verification token in the request matches our app's settings
    if SLACK_VERIFICATION_TOKEN != slack_event.get("token"):
        message = "Invalid Slack verification token: %s \nsandlibrarian has: \
                   %s\n\n" % (slack_event["token"], SLACK_VERIFICATION_TOKEN)
        # By adding "X-Slack-No-Retry" : 1 to our response headers, we turn off
        # Slack's automatic retries during development.
        make_response(message, 403, {"X-Slack-No-Retry": 1})

    # ====== Process Incoming Events from Slack ======= #
    # If the incoming request is an Event we've subcribed to
    if "event" in slack_event:
        event_type = slack_event["event"]["type"]
        # Then handle the event by event_type and have your bot respond
        return _event_handler(event_type, slack_event, mendeley_session)
    # If our bot hears things that are not events we've subscribed to,
    # send a quirky but helpful error response
    return make_response("[NO EVENT IN SLACK REQUEST] These are not the droids you're looking for.", 404, {"X-Slack-No-Retry": 1})


if __name__ == "__main__":
    app.run(host='0.0.0.0')
