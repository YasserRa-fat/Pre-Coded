Here is a simple example of a main.js file for a Django project:

```
// main.js

// When the DOM is ready, run this function
$(document).ready(function() {

  // Add smooth scrolling to all links
  $('a').on('click', function(event) {

    // Make sure this.hash has a value before overriding default behavior
    if (this.hash !== '') {

      // Prevent default anchor click behavior
      event.preventDefault();

      // Store hash
      var hash = this.hash;

      // Using jQuery's animate() method to add smooth page scroll
      // The optional number (800) specifies the number of milliseconds it takes to scroll to the specified area
      $('html, body').animate({
        scrollTop: $(hash).offset().top
      }, 800, function(){

        // Add hash (#) to URL when done scrolling (default click behavior)
        window.location.hash = hash;
      });
    } // End if
  });
});
```

This code adds smooth scrolling to all links on the page, so that when a user clicks on a link, the page smoothly scrolls to the corresponding section. This can be useful for single-page websites or websites with a lot of sections.

To use this code in your Django project, you will need to include it in your HTML templates and make sure that the jQuery library is loaded. You can do this by adding the following line to the head of your HTML templates:

```
<script src="{% static 'js/jquery.min.js' %}"></script>
```

You will also need to include the main.js file in the head of your HTML templates, like this:

```
<script src="{% static 'js/main.js' %}"></script>
```

Make sure that the static files are correctly configured in your Django project, and that the js/ directory is included in the STATICFILES\_DIRS setting. You can find more information about static files in the Django documentation: <https://docs.djangoproject.com/en/3.2/howto/static-files/>