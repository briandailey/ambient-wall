#!/usr/bin/env python

__author__ = "Brian Dailey"

import logging
import oauth
import models
import os
import api_keys

from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp import util
from google.appengine.ext.webapp import template

class MainHandler(webapp.RequestHandler):

 	def get(self, mode=""):
    
		client = oauth.TwitterClient(api_keys.SETTINGS['twitter']['application_key'], api_keys.SETTINGS['twitter']['application_secret'], api_keys.SETTINGS['twitter']['callback_url'])

		if mode == "login":
			return self.redirect(client.get_authorization_url())

		if mode == "verify":
			auth_token = self.request.get("oauth_token")
			auth_verifier = self.request.get("oauth_verifier")
			user_info = client.get_user_info(auth_token, auth_verifier=auth_verifier)
			logging.debug(user_info)
			prefs = models.UserPrefs(user=users.get_current_user(),
							twitter_token=user_info['token'],
							twitter_secret=user_info['secret'])
			prefs.put()
			column = models.Column(user=users.get_current_user(),
							service='twitter',
							column_type='core',
							column_description='Friends Timeline',
							column_data='friends-timeline')
			column.put()
							

			return self.redirect('/dashboard/')

		user = users.get_current_user()
		if user:
			userpref = models.UserPrefs.gql("WHERE user = :user LIMIT 1", user=users.get_current_user()).get()
			if userpref:
				return self.redirect('/dashboard/');

		path = os.path.join(os.path.dirname(__file__), 'templates', 'index.html')
		self.response.out.write(template.render(path, { 'login_url': users.create_login_url('/dashboard/') }))


def main():
  application = webapp.WSGIApplication([('/(.*)', MainHandler)],
                                       debug=True)
  util.run_wsgi_app(application)


if __name__ == '__main__':
  main()
