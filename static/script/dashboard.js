$.fn.focusEnd = function() {
	var end = $(this).val().length;
	return this.each(function() {
		if(this.setSelectionRange) {
			this.focus();
			this.setSelectionRange(end, end);
		} else if(this.createTextRange) {
			var range = this.createTextRange();
			range.collapse(true);
			range.moveEnd('character', end);
			range.moveStart('character', end);
			range.select();
		}
	});
};

$(document).ready(function() {

	// reload each column per user's preferences
	$('.twitter').each(function() {
		var id = $(this).attr('id');
		dashboard.setReloadInterval(id);
	});

	$('a.twitpic').live('click', function() {
	});

	$('a.twitter-user').live('click', function() {
		$.post('/dashboard/columns/?format=full',
		{ 'column_type': 'twitter-user', 
			'column_user_data': $(this).attr('rel'),
			'request-type': 'ajax'
		},
		function (data) {
			$('#all-columns').append(data);
			dashboard.reset();
		});
		return false;
	});


	dashboard.title = document.title;

	// resize the columns to fit the window size
	dashboard.resizeColumns();

	$('.reply-to').live('click', function() { dashboard.replyTo(this); return false; });
	$('.retweet').live('click', function() { dashboard.retweet(this); return false; });
	$('.direct-message').live('click', function() { dashboard.directMessage(this); return false; });

	$('#status-box').keyup(function() { 
		dashboard.getCharCount(); 
		// if edited, blank out retweet id.
		$('#retweet_id').val('');
	});

	$('#status form').submit(function() {
		dashboard.clearStatusMsg();
		$('#status-msg').html('<img src="/static/img/loading.gif" />');
		$.post(
			$(this).attr('action'),
			$(this).serialize(),
			function(data) {
				$('#status-msg').removeClass('loading');
				if (data == 'success') {
					$('#status-box').val('');
					$('#character-count').text('');
					$('#status-msg').addClass('success').html('Status updated successfully.');
					setTimeout('dashboard.clearStatusMsg();', 2000);
				} else {
					$('#status-msg').addClass('error').html(data);
					setTimeout('dashboard.clearStatusMsg();', 2000);
				}
				return false;
			}
		);
		return false;
	});

	$('.item').live('mouseover', function() {
		$(this).find('.tools').show();
	}).live('mouseout', function() {
		$(this).find('.tools').hide();
	});
	$('.column-title').live('mouseover', function() {
		$(this).find('.tools').show();
	}).live('mouseout', function() {
		$(this).find('.tools').hide();
	});

	$('a.reload').live('click', function() {
		var key = $(this).parents('.column').attr('id');
		dashboard.reloadColumn(key, { 'since_id': $('#'+key).find('.item:first').attr('rel'), 'use_memcached': 'false' });
		// Reset intervals
		clearInterval('dashboard.reloadColumn("'+key+'")');
		dashboard.setReloadInterval(key);
		return false;
	});

	$('a.remove').live('click', function() {
		if (!confirm('Are you sure you want to remove this column?')) {
			return false;
		}
		var key = $(this).parents('.column').attr('id');
		$.post('/dashboard/columns/',
			{
				action: 'delete',
				key: key
			},
			function(data) {
				if (data == 'success') {
					$('#' + key).remove();
				}
		});
		return false;
	});
	
	$('div.column .column-content').scroll(function() {
		// scrool to bottom of window. get more results from twitter.
		var elem = $(this);
		if (elem[0].scrollHeight - elem.scrollTop() == elem.outerHeight()) {
			if ($(this).parents('.column').hasClass('twitter') == false) {
				return false;
			}
			if ($('#status-msg .loading-indicator').length != 0) {
				return false;
			}
			var id = $(this).parents('.column').attr('id');
			var max_id = $(this).find('.item:last').attr('rel') - 1;
			dashboard.loading();
			dashboard.reloadColumn(id, { 'max_id': max_id, 'use_memcached': 'false' }, { 'results_action': 'append' });
			
		}
	});

});

$(window).resize(function() {
	dashboard.resizeColumns();
});

var dashboard = {
	loading: function() {
		$('#status-msg').html('<img src="/static/img/loading.gif" class="loading-indicator" />');
	},
	reloadColumn: function(id) {
		var params = {};
		var options = {};
		if (arguments[1]) { 
			params = arguments[1]; 
		} else {
			params = { 'since_id': $('#'+id+' .column-content .item:first').attr('rel') };
		}
		if (arguments[2]) { options = arguments[2]; }

		dashboard.loading();
		$.get('/dashboard/column/' + id, params, function(data) {
			if (options['results_action'] == 'append') {
				$('#' + id + ' .column-content').append(data);
			} else {
				$('#' + id + ' .column-content').prepend(data);
			}
			var twitter_api_remaining_hits = $('#' + id + ' input[name=twitter_api_remaining_hits]').val();
			if (twitter_api_remaining_hits) {
				$('#twitter-api-remaining-hits').text(twitter_api_remaining_hits);
			}
			$('#status-msg').html('');
			if ($('#' + id).children('.new')) {
				dashboard.titleNewMessages();
			}
			dashboard.clearStatusMsg();
			dashboard.reset();
		});
	},
	reset: function() {
			$('.rounded').corner();
			$('#all-columns .hidden').hide();
			dashboard.resizeColumns();
	},
	titleNewMessages: function() {
		document.title = '*' + dashboard.title;
		setTimeout('document.title=dashboard.title;', 15000);
	},
	resizeColumns: function() {
		var count = $('div.column .column-content').length;
		var viewportWidth = $(window).width();
		var viewportHeight = $(window).height();
		$('div.column .column-content').each(function() {
			$(this).css('height', viewportHeight-150);
			// if (count < 3) {
				// $(this).parent('.column').css('width', (viewportWidth / count)-50);
			// }
		});
	},
	clearStatusMsg: function() {
		$('#status-msg').removeClass('error').removeClass('success').removeClass('notice').text('');
	},
	replyTo: function(item) {
		var status_id = $(item).parents('.item').attr('rel');
		var screen_name = $(item).parents('.item').find('.user-screenname').text().trim();
		if ($('#status').css('display') == 'none') { $('#status').fadeIn('fast'); }
		$('#status-box').val('@' + screen_name + ' ');
		$('#status input[name=in_reply_to_status_id]').val(status_id);
		$('#status-box').focusEnd();
		return false;
	},
	retweet: function(item) {
		var status_id = $(item).parents('.item').attr('rel');
		var screen_name = $(item).parents('.item').find('.user-screenname').text().trim();
		if ($('#status').css('display') == 'none') { $('#status').fadeIn('fast'); }
		$('#status input[name=retweet_id]').val(status_id);
		$('#status-box').val('RT: @' + screen_name + ' ' + $(item).parents('.item').find('.text').text());
		$('#status-msg').addClass('notice').text('Editing this message will post it as a "classic" retweet.');
		$('#status-box').focusEnd();
		dashboard.getCharCount();
		return false;
	},
	directMessage: function(item) {
		var screen_name = $(item).parents('.item').find('.user-screenname').text().trim();
		if ($('#status').css('display') == 'none') { $('#status').fadeIn('fast'); }
		$('#status-box').val('d ' + screen_name + ' ');
		$('#status-box').focusEnd();
		dashboard.getCharCount();
		return false;
	},
	getCharCount: function() {
		var box = $('#status-box');
		var ln = box.val().length;
		if (ln > 140) {
			box.css('background-color', '#fbe3e4');
		} else {
			box.css('background-color', '');
		}
		if (ln > 0) {
			$('#character-count').text(ln + '/140 characters.');
		} else {
			$('#character-count').text('');
		}
	},
	setReloadInterval: function(id) {
		var refresh_rate = parseInt($('#'+id).attr('rel'));
		if (isNaN(refresh_rate)) { refresh_rate = 120; }
		var interval = refresh_rate * 1000;
		// todo - pass an array instead so we can 
		// combine those with the same interval.
		setInterval('dashboard.reloadColumn("'+id+'")', interval);
	},
	title: ''
}
