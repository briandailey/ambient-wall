#!/usr/bin/env python

__author__ = "Brian Dailey"

import logging
import oauth
import models
import os
import api_keys
import re

from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp import util
from google.appengine.ext.webapp import template
from django.utils import simplejson as json
from google.appengine.api import memcache
from google.appengine.ext import db
from google.appengine.ext.db import Key
from google.appengine.api import quota

logging.getLogger().setLevel(logging.DEBUG)

try:
	from config import OAUTH_APP_SETTINGS
except:
	pass
							

class ManageColumns(webapp.RequestHandler):
	templateValues = {}

	def setColumnTypeDescriptions(self):
		self.column_type_descriptions = {
			"friends-timeline": "Your Friends Timeline",
			"mentions": "Mentions Of You",
			"direct-messages": "Direct Messages To You",
			# "retweets-of-me": "Retweets Of Me",
		}
	
	def get(self, key=""):
		logging.info('Accessing dashboard management')


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

			elif self.request.get('column_type') == 'twitter-user':
				column_data = self.request.get('column_user_data')
				column_description=('@%s' % self.request.get('column_user_data'))

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

			if self.request.get('request-type') == 'ajax':
				return self.redirect('/dashboard/column/' + str(column.key()))
			else:
				return self.redirect('/dashboard/columns/?msg=added')

class ColumnResults(webapp.RequestHandler):

	def get(self, key=""):

		logging.info('Accessing column results')
		handler = ColumnHandler()
		handler.getTwitterRateLimit()

		userprefs = models.UserPrefs.gql("WHERE user = :user LIMIT 1", user=users.get_current_user()).get()

		use_memcached = True
		# use_memcached = False

		if self.request.get('use_memcached'):
			use_memcached = False 

		# start = quota.get_request_cpu_usage()

		results = handler.getColumnResults(key, userprefs, use_memcached)
		column = models.Column.gql('WHERE __key__ = :1', Key(key)).get()

		column = {
			'results': results,
			'column': column
		}

		# end = quota.get_request_cpu_usage()
		# logging.info("Column reload cost %d megacycles." % (start - end))
		path = os.path.join(os.path.dirname(__file__), 'templates', 'column.html')
		self.response.out.write(template.render(path, { 'column': column, 'userprefs': userprefs }))

class ColumnHandler(object):

	def getTwitterRateLimit(self):
		userprefs = models.UserPrefs.gql("WHERE user = :user LIMIT 1", user=users.get_current_user()).get()
		if userprefs is None or userprefs.twitter_token is None:
			return False

		client = oauth.TwitterClient(api_keys.SETTINGS['twitter']['application_key'], api_keys.SETTINGS['twitter']['application_secret'], api_keys.SETTINGS['twitter']['callback_url'])
		try:
			rate_limit_status = client.make_request(url="http://twitter.com/account/rate_limit_status.json", token=userprefs.twitter_token, secret=userprefs.twitter_secret)
			rate_limit_status = json.loads(rate_limit_status.content)
			if type(rate_limit_status).__name__ != 'list' and rate_limit_status.has_key('error'):
					return False
		except:
			return False
	
		userprefs.twitter_api_remaining_hits = str(rate_limit_status["remaining_hits"])
		userprefs.twitter_reset_time = str(rate_limit_status["reset_time_in_seconds"])
		userprefs.twitter_hourly_limit = str(rate_limit_status["hourly_limit"])
		userprefs.put()
	

	def getColumnResults(self, key, userprefs, use_memcached):
		column = models.Column.gql('WHERE __key__ = :1', Key(key)).get()
		if column == None:
			return False

		memcached_key = 'column-results-' + key

		if use_memcached == True:
			# logging.info('Returning results from memcached.')
			results = memcache.get(memcached_key)
			if results:
				return results

		if column.service == 'twitter':
			if userprefs is None or userprefs.twitter_token is None:
				return False

			client = oauth.TwitterClient(api_keys.SETTINGS['twitter']['application_key'], api_keys.SETTINGS['twitter']['application_secret'], api_keys.SETTINGS['twitter']['callback_url'])
			additional_params = { 'count': 50 }

			if column.column_type == 'core':
				if column.column_data == 'friends-timeline':
					url = "http://twitter.com/statuses/home_timeline.json"
				elif column.column_data == 'mentions':
					url = 'http://twitter.com/statuses/mentions.json'
				elif column.column_data == 'direct-messages':
					url = 'http://twitter.com/direct_messages.json'
				elif column.column_data == 'retweets-of-me':
					url = 'http://api.twitter.com/1/statuses/retweets_of_me.json'
				else: # unknown
					logging.error('Unknown column type ' + column.column_type)
					return False

			elif column.column_type == 'search':
				url = 'http://search.twitter.com/search.json'
				additional_params['q'] = column.column_data

			elif column.column_type == 'twitter-user':
				url = 'http://api.twitter.com/1/statuses/user_timeline.json'
				additional_params['screen_name'] = column.column_data
			else: # unknown
				logging.error('Unknown column type ' + column.column_type)
				return False

			try:
				results = client.make_request(url=url, token=userprefs.twitter_token, secret=userprefs.twitter_secret, additional_params=additional_params)
				results = json.loads(results.content)
			except:
				return False

			if type(results).__name__ != 'list' and results.has_key('error'):
				return False

			if column.column_type == 'search':
				# twitter search results are cocooned inside
				logging.info('Search type.')
				results = results["results"]

			results = self.__transformTwitterResults(results, column)

		if not memcache.add(memcached_key, results, column.refresh_rate):
			logging.error("Memcache save to " + memcached_key + " for " + str(column.refresh_rate) + " seconds failed.")

		# save the last id returned.
		if type(results).__name__ == 'list' and len(results) > 0 and results[0]['key']:
			# logging.error('Saving last key returned: ' + str(results[0]['key']))
			column.last_id_returned = str(results[0]['key'])
			column.put()

		return results
	
	def __transformTwitterResults(self, items, column):
		# cannot be a dictionary because it must be sequential.
		transformative_regexes = (
			# links
			( r'<a href="\1" target="blank">\1</a>', re.compile("(https?://([-\w\.]+)+(:\d+)?(/([\w/_\.-]*(\?\S+)?)?)?)")),
			# mentions
			( r'@<a href="http://www.twitter.com/\1" class="twitter-user" rel="\1" target="blank">\1</a>', re.compile('@(\w*)')),
			# twitpic links			
			( r'href="http://twitpic.com/\1" rel="\1" class="twitpic" target="blank">\2<', re.compile('href="http://twitpic.com/(\w*)">([^<]*)<')),
		)

		mute_regexes = ()
		if column.mute is not None and len(column.mute) > 0:
			mute_regexes = (
				( 'screen_name', re.compile(column.mute, re.IGNORECASE) ),
				( 'text', re.compile(column.mute, re.IGNORECASE) ),
			)
			
		results = []

		if column.column_type == 'core' or column.column_type == 'twitter-user':
			if column.column_data == 'direct-messages':
				for item in items: 
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
					if self.__checkMutes(row, column, mute_regexes):
						results.append(self.__applyRegexes(row, column, transformative_regexes))
			else:
				for item in items: 
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
					if self.__checkMutes(row, column, mute_regexes):
						results.append(self.__applyRegexes(row, column, transformative_regexes))
		elif column.column_type == 'search':
			logging.info('Search column, applying tranformations.')
			ge = re.compile('(&gt;)')
			le = re.compile('(&lt;)')
			for item in items: 
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
				if self.__checkMutes(row, column, mute_regexes):
					results.append(self.__applyRegexes(row, column, transformative_regexes))

		return results

	def __checkMutes(self, row, column, mute_regexes):
		# filter out muted items.
		approved = True
		for regex in mute_regexes:
			if re.search(regex[1], row[regex[0]]):
				approved = False

		return approved
	
	def __applyRegexes(self, row, column, transformative_regexes):
		# transformative regexes
		for regex in transformative_regexes:
			row['text'] = regex[1].sub(regex[0], row['text'])

		if str(row['key']) > column.last_id_returned:
			row['new_message'] = True
		else:
			row['new_message'] = False

		return row

class MainDashboard(webapp.RequestHandler):

	def get(self):
		# logging.info('Accessing dashboard')
		user = users.get_current_user()

		handler = ColumnHandler()
		handler.getTwitterRateLimit()

		columns = models.Column.gql("WHERE user = :user ORDER BY column_order ASC", user=users.get_current_user(), keys_only=True)
		userprefs = models.UserPrefs.gql("WHERE user = :user LIMIT 1", user=users.get_current_user()).get()

		column_results = []

		for column in columns:
			results = handler.getColumnResults(str(column.key()), userprefs, True)
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
				(r'/dashboard/columns/', ManageColumns),
				(r'/dashboard/column/(\w*)', ColumnResults),
				(r'/dashboard/post/', PostStatus),
				(r'/dashboard/$', MainDashboard),
			], debug=True)
  util.run_wsgi_app(application)


if __name__ == '__main__':
  main()
