Here is a simple example of a main.js file for a Django project:

```
// main.js

// When the DOM is ready, run this function
$(document).ready(function() {
  // Add a click event listener to the button with the id "myButton"
  $('#myButton').on('click', function() {
    // Prevent the default form submission behavior
    event.preventDefault();

    // Get the value of the input field with the id "myInput"
    var inputValue = $('#myInput').val();

    // Log the input value to the console
    console.log('Input value:', inputValue);
  });
});
```

This code adds a click event listener to a button with the id "myButton", and when the button is clicked, it prevents the default form submission behavior, gets the value of an input field with the id "myInput", and logs the value to the console.

Note that this code assumes that you have already included the jQuery library in your project. If you have not, you can add it by adding the following line to the head of your HTML file:

```
<script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
```

You can also download the jQuery library and include it locally in your project if you prefer.