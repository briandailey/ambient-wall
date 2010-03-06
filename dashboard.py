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
from django.utils import simplejson as json
from google.appengine.api import memcache
from google.appengine.ext import db
from google.appengine.ext.db import Key

logging.getLogger().setLevel(logging.DEBUG)

try:
	from config import OAUTH_APP_SETTINGS
except:
	pass
							

class ManageColumns(webapp.RequestHandler):

	templateValues = {}

	def setColumnTypeDescriptions(self):
		self.column_type_descriptions = {
			"friends-timeline": "Friends Timeline",
			"mentions": "Mentions",
			"direct-messages": "Direct Messages",
			# "retweets-of-me": "Retweets Of Me",
		}
	
	def get(self, key=""):

		templateValues = {}
	
		userprefs = models.UserPrefs.gql("WHERE user = :user LIMIT 1", user=users.get_current_user()).get()
		templateValues['userprefs'] =  userprefs

		if self.request.get('msg') == 'saved':
			templateValues['msg'] = 'Global preferences were saved.'
		elif self.request.get('msg') == 'added':
			templateValues['msg'] = 'New column was added.'

		if self.request.get('err') == 'dupe':
			templateValues['err'] = 'You may only have one column of that type.'

		if userprefs is None or userprefs.twitter_token is None:
			templateValues['twitter_authenticated'] = False
		else:
			templateValues['twitter_authenticated'] = True

		self.setColumnTypeDescriptions()

		if key:
			column = models.Column.gql('WHERE __key__ = :1 AND user = :2', Key(key), users.get_current_user()).get()
		else:
			columns = models.Column.gql("WHERE user = :user ORDER BY column_order ASC", user=users.get_current_user())
			templateValues['columns'] = columns
			templateValues['column_count'] = columns.count()
			templateValues['column_type_descriptions'] = self.column_type_descriptions
			path = os.path.join(os.path.dirname(__file__), 'templates', 'manage_columns.html')
			self.response.out.write(template.render(path, templateValues))
	
	def post(self):

		self.setColumnTypeDescriptions()

		if self.request.get('action') == 'reorder':
			list = self.request.get_all('list[]')
			for i in range(len(list)):
				key = list[i]
				column = models.Column.gql('WHERE __key__ = :1', Key(key)).get()
				column.column_order = i
				column.put()
			return self.response.out.write('success')
		elif self.request.get('key') and self.request.get('action') == 'delete':
			key = self.request.get('key')
			column = models.Column.gql('WHERE __key__ = :1', Key(key)).get()
			column.delete()
			return self.response.out.write('success')
		elif self.request.get('key') and self.request.get('action') == 'edit':

			key = self.request.get('key')

			column = models.Column.gql('WHERE __key__ = :1', Key(key)).get()

			column.mute = self.request.get('mute')

			try:
				refresh_rate = int(self.request.get('refresh_rate'))
			except ValueError:
				refresh_rate = 120
			column.refresh_rate = refresh_rate

			column.put()

			# clear memcached
			memcache.delete('column-results-' + str(column.key()))

			return self.response.out.write('success')
		else: # add new column
			if self.request.get('column_type') == 'core':
				# check to see if such a column already exists.
				column = models.Column.gql('WHERE user = :1 and column_data = :2', users.get_current_user(), self.request.get('column_data'))
				if column.count() > 0:
					return self.redirect('/dashboard/columns/?err=dupe')

				column_data = self.request.get('column_data')
				column_description=self.column_type_descriptions[self.request.get('column_data')]

			elif self.request.get('column_type') == 'search':
				column_data = self.request.get('column_search_data')
				column_description=('Search: "%s"' % self.request.get('column_search_data'))

			try:
				refresh_rate = int(self.request.get('refresh_rate'))
			except ValueError:
				refresh_rate = 120

			column = models.Column(user=users.get_current_user(),
														column_type=self.request.get('column_type'),
														column_description=column_description,
														column_data=column_data,
														refresh_rate=refresh_rate,
														mute=self.request.get('mute'))
			column.put()
			return self.redirect('/dashboard/columns/?msg=added')

class ColumnResults(webapp.RequestHandler):
	def get(self, key=""):

		handler = ColumnHandler()
		handler.getTwitterRateLimit()

		userprefs = models.UserPrefs.gql("WHERE user = :user LIMIT 1", user=users.get_current_user()).get()

		use_memcached = True

		if self.request.get('use_memcached'):
			use_memcached = False 

		results = handler.getColumnResults(key, userprefs, use_memcached)
		column = {
			'results': results
		}

		path = os.path.join(os.path.dirname(__file__), 'templates', 'column.html')
		self.response.out.write(template.render(path, { 'column': column, 'userprefs': userprefs }))

class ColumnHandler(object):

	# TODO - track # of requests for twitter API
	def getTwitterRateLimit(self):
		userprefs = models.UserPrefs.gql("WHERE user = :user LIMIT 1", user=users.get_current_user()).get()
		if userprefs is None or userprefs.twitter_token is None:
			return False

		client = oauth.TwitterClient(api_keys.SETTINGS['twitter']['application_key'], api_keys.SETTINGS['twitter']['application_secret'], api_keys.SETTINGS['twitter']['callback_url'])
		rate_limit_status = client.make_request(url="http://twitter.com/account/rate_limit_status.json", token=userprefs.twitter_token, secret=userprefs.twitter_secret)
		rate_limit_status = json.loads(rate_limit_status.content)
		if type(rate_limit_status).__name__ != 'list' and rate_limit_status.has_key('error'):
				return False
		# logging.error(rate_limit_status)
	
		userprefs.twitter_api_remaining_hits = str(rate_limit_status["remaining_hits"])
		userprefs.twitter_reset_time = str(rate_limit_status["reset_time_in_seconds"])
		userprefs.twitter_hourly_limit = str(rate_limit_status["hourly_limit"])
		userprefs.put()
	

	def getColumnResults(self, key, userprefs, use_memcached=True):
		column = models.Column.gql('WHERE __key__ = :1', Key(key)).get()
		if column == None:
			return False

		memcached_key = 'column-results-' + key

		if use_memcached:
			results = memcache.get(memcached_key)
			if results:
				return results

		if column.service == 'twitter':
			if userprefs is None or userprefs.twitter_token is None:
				return False

			client = oauth.TwitterClient(api_keys.SETTINGS['twitter']['application_key'], api_keys.SETTINGS['twitter']['application_secret'], api_keys.SETTINGS['twitter']['callback_url'])

			if column.column_type == 'core':
				if column.column_data == 'friends-timeline':
					url = "http://twitter.com/statuses/friends_timeline.json"
				elif column.column_data == 'mentions':
					url = 'http://twitter.com/statuses/mentions.json'
				elif column.column_data == 'direct-messages':
					url = 'http://twitter.com/direct_messages.json'
				elif column.column_data == 'retweets-of-me':
					url = 'http://api.twitter.com/1/statuses/retweets_of_me.json'
				else: # unknown
					logging.error('Unknown column type ' + column.column_type)
					return False

				try:
					results = client.make_request(url=url, token=userprefs.twitter_token, secret=userprefs.twitter_secret)
				except:
					return False

				results = json.loads(results.content)
				if type(results).__name__ != 'list' and results.has_key('error'):
					return False

				results = self.__transformTwitterResults(results, column)

			elif column.column_type == 'search':
				search_url = 'http://search.twitter.com/search.json'
				try:
					search_results = client.make_request(url=search_url, token=userprefs.twitter_token, secret=userprefs.twitter_secret, additional_params={ 'q': column.column_data })
				except:
					return False
				search_results = json.loads(search_results.content)
				if type(search_results).__name__ != 'list' and search_results.has_key('error'):
					return False

				results = self.__transformTwitterResults(search_results["results"], column)

		if not memcache.add(memcached_key, results, column.refresh_rate):
			logging.error("Memcache save to " + memcached_key + " for " + str(column.refresh_rate) + " seconds failed.")

		# save the last id returned.
		if len(results) > 0 and results[0]['key']:
			# logging.error('Saving last key returned: ' + str(results[0]['key']))
			column.last_id_returned = str(results[0]['key'])
			column.put()

		return results
	
	def __transformTwitterResults(self, items, column):
		import re
		replies = re.compile('@(\w*)')
		twitpic = re.compile('href="http://twitpic.com/(\w*)">([^<]*)<')
		ge = re.compile('(&gt;)')
		le = re.compile('(&lt;)')
		urlfinders = [
			re.compile("(https?://([-\w\.]+)+(:\d+)?(/([\w/_\.-]*(\?\S+)?)?)?)"),
		]
		new_message = True

		if column.mute is not None and len(column.mute) > 0:
			mute = re.compile(column.mute, re.IGNORECASE)
		results = []

		for item in items: 
				if column.column_type == 'core':
					if column.column_data == 'direct-messages':
						row = {
							'key': item['id'],
							'profile_image_url': item['sender']['profile_image_url'],
							'name': item['sender']['name'],
							'link': 'http://www.twitter.com/' + item['sender']['screen_name'] + '/status/' + str(item['id']),
							'screen_name': item['sender']['screen_name'],
							'screen_name_link': ('http://twitter.com/%s' % item['sender']['screen_name']),
							'text': item['text'],
							'in_reply_to_status_id': '',
							'in_reply_to_screen_name': '',
							'created_at': item['created_at'],
							'source': '',
						}
					else:
						row = {
							'key': item['id'],
							'profile_image_url': item['user']['profile_image_url'],
							'name': item['user']['name'],
							'link': 'http://www.twitter.com/' + item['user']['screen_name'] + '/status/' + str(item['id']),
							'screen_name': item['user']['screen_name'],
							'screen_name_link': ('http://twitter.com/%s' % item['user']['screen_name']),
							'text': item['text'],
							'in_reply_to_status_id': item['in_reply_to_status_id'],
							'in_reply_to_screen_name': item['in_reply_to_screen_name'],
							'created_at': item['created_at'],
							'source': item['source'],
						}
				elif column.column_type == 'search':
					# for some reash search results 'source' is escaped html. unescape it.
					item['source'] = ge.sub(r'>', item['source'])
					item['source'] = le.sub(r'<', item['source'])
					row = {	
						'key': item['id'],
						'profile_image_url': item['profile_image_url'],
						'name': item['from_user'],
						'link': 'http://www.twitter.com/' + item['from_user'] + '/status/' + str(item['id']),
						'screen_name': item['from_user'],
						'screen_name_link': ('http://twitter.com/%s' % item['from_user']),
						'text': item['text'],
						'in_reply_to_status_id': item['to_user_id'],
						'in_reply_to_screen_name': None,
						'created_at': item['created_at'],
						'source': item['source'],
					}

				# filter out muted items.
				if column.mute is not None and len(column.mute) > 0:
					if re.search(mute, row['text']):
						continue
					if re.search(mute, row['screen_name']):
						continue

				# linkify http links
				for i in urlfinders:
					row['text'] = i.sub(r'<a href="\1" target="blank">\1</a>', row['text'])

				# linkify screen names.	
				row['text'] = replies.sub(r'@<a href="http://www.twitter.com/\1" class="twitter-user" rel="\1">\1</a>', row['text'])

				row['text'] = twitpic.sub(r'href="http://twitpic.com/\1" rel="\1" class="twitpic">\2<', row['text'])

				if str(row['key']) == column.last_id_returned:
					new_message = False

				row['new_message'] = new_message
				
				results.append(row)

		return results


class Dashboard(webapp.RequestHandler):

	def get(self):
		user = users.get_current_user()

		handler = ColumnHandler()
		handler.getTwitterRateLimit()

		columns = models.Column.gql("WHERE user = :user ORDER BY column_order ASC", user=users.get_current_user(), keys_only=True)
		userprefs = models.UserPrefs.gql("WHERE user = :user LIMIT 1", user=users.get_current_user()).get()

		column_results = []

		for column in columns:
			results = handler.getColumnResults(str(column.key()), userprefs)
			if results is False:
					results = None
			column_results.append({
				'results': results,
				'column': column,
			})
		
		path = os.path.join(os.path.dirname(__file__), 'templates', 'dashboard.html')
		self.response.out.write(template.render(path, { 
				'column_results': column_results ,
				'user': user,
				'userprefs': userprefs,
				'logout_url': users.create_logout_url("/"),
		}))

class PostStatus(webapp.RequestHandler):

	def post(self):

		userprefs = models.UserPrefs.gql("WHERE user = :user LIMIT 1", user=users.get_current_user()).get()

		client = oauth.TwitterClient(api_keys.SETTINGS['twitter']['application_key'], api_keys.SETTINGS['twitter']['application_secret'], api_keys.SETTINGS['twitter']['callback_url'])

		from google.appengine.api import urlfetch

		if self.request.get('retweet_id'):
			result = client.make_request(url="http://api.twitter.com/1/statuses/retweet/" + str(self.request.get('retweet_id')) + ".json", 
				token=userprefs.twitter_token, 
				secret=userprefs.twitter_secret, 
				additional_params={}, 
				protected=False, 
				method=urlfetch.POST)
		elif self.request.get('status'):
			additional_params = {
				'status': self.request.get('status'),
			}

			if self.request.get('in_reply_to_status_id'):
				additional_params['in_reply_to_status_id'] = self.request.get('in_reply_to_status_id')

			result = client.make_request(url="http://twitter.com/statuses/update.json", 
				token=userprefs.twitter_token, 
				secret=userprefs.twitter_secret, 
				additional_params=additional_params, 
				protected=False, 
				method=urlfetch.POST)

		else:
			self.response.set_status(500)
			return self.response.out.write(result.error)

		if result.status_code == 403:
			self.response.out.write('API limit maxed out. Please wait a moment and try again.')
		else:
			result = json.loads(result.content)
			if hasattr(result, 'error'):
				self.response.set_status(500)
				return self.response.out.write(result.error)
			else:
				self.response.out.write('success')
		


def main():
  application = webapp.WSGIApplication( [
				('/dashboard/', Dashboard),
				('/dashboard/columns/', ManageColumns),
				('/dashboard/column/(.*)', ColumnResults),
				('/dashboard/post/', PostStatus),
			], debug=True)
  util.run_wsgi_app(application)


if __name__ == '__main__':
  main()
