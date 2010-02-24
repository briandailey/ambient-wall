$(document).ready(function() {
	$('a.delete').live('click', function() {
		var key = $(this).attr('rel');
		$.post('/dashboard/columns/',
			{
				action: 'delete',
				key: key
			},
			function(data) {
				if (data == 'success') {
					$('#list-' + key).remove();
				}
		});
		$('#msg').html('<div class="success">Column deleted.</div>');
		setTimeout('$("#msg").html("")', 5000);
		return false;
	});

	$('form.edit').submit(function() {
		var form = $(this);
		$.post(form.attr('action'),
		form.serialize(),
		function (data) {
				if (data == 'success') {
					$('#msg').html('<div class="success">Changes saved.</div>');
					form.parent('.edit-column').toggle();
					setTimeout('$("#msg").html("")', 5000);
				}
		});
		return false;
	});

	$('#column_type').change(function() {
		var type = $(this).val();
		$('.column-type').hide();
		$('.column-type-' + type).show();
	});

	$('#columns').sortable({
		opacity: 0.6,
		cursor: 'move',
		handle: '.handle',
		update: function() {
			var list = $(this).sortable('serialize');
			$.post('/dashboard/columns/',
				list + '&action=reorder',
				function (data) {
					if (data == 'success') {
						$('#msg').html('<div class="success">Column order saved.</div>');
						setTimeout('$("#msg").html("")', 5000);
					}
			});
		}
	});

});
