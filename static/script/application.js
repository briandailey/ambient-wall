$(document).ready(function() {
	$('.rounded').corner();
	$('div.hidden').hide();

	$('a.toggle').live('click', function() {
		var id = $(this).attr('rel');
		$('#' + id).toggle();
		return false;
	});

	$.ajax({
		error: function(request, status, error) {
			if ($('#status-msg')) {
				$('#status-msg').addClass('error').text('Crikey! Somewhere we blew a gasket. We recommend reloading the page.');
			}
		}
	});
});
