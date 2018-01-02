install mendeley with patched pdf create

how to set-up things in docker for deployment:
docker build -t sandlibrarian .
create a docker-compose

# How to set-up:

- Set the redirects on dev.slack to 'your-url'
  - event notifications
  - oauth
  - interactive message-actions
- Set the oauth redirect on dev.mendeley to 'your-url/oauth'
- make sure all relevant environment variables are set (see docker-compose)

# TODO:

- make token renewal easier
- Confirm that mendeley is up and running
