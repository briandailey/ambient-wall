from google.appengine.ext import db

class UserPrefs(db.Model):
	user = db.UserProperty(required=True)
	twitter_token = db.StringProperty(required=True)
	twitter_secret = db.StringProperty(required=True)
	twitter_api_remaining_hits = db.StringProperty()
	twitter_reset_time = db.StringProperty()
	twitter_hourly_limit = db.StringProperty()

class Column(db.Model):
	user = db.UserProperty(required=True)
	service = db.StringProperty(default='twitter')
	column_type = db.StringProperty(required=True)
	column_description = db.StringProperty(required=True)
	column_data = db.StringProperty()
	column_order = db.IntegerProperty(default=1)
	mute = db.StringProperty()
	refresh_rate = db.IntegerProperty(default=120)
	last_updated_at = db.DateTimeProperty(auto_now=True)
	last_id_returned = db.StringProperty()
