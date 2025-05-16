Here is a simple example of a main.js file for a Django project. This file simply toggles the visibility of an element with the id "myElement" when the button with the id "myButton" is clicked.

```
// Get the button and element
const button = document.getElementById('myButton');
const element = document.getElementById('myElement');

// Toggle the visibility of the element when the button is clicked
button.addEventListener('click', () => {
  if (element.style.display === 'none') {
    element.style.display = 'block';
  } else {
    element.style.display = 'none';
  }
});
```

This is just a basic example, and you can customize it to fit the needs of your Django project. Make sure to include this file in your HTML templates using the `{% static %}` template tag, like so:

```
<script src="{% static 'js/main.js' %}"></script>
```