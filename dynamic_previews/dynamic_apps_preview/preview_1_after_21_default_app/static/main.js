```javascript
document.addEventListener('DOMContentLoaded', function() {
    var ctx = document.getElementById('analyticsChart').getContext('2d');
    var analyticsChart = new Chart(ctx, {
        type: 'line',
        data: comments_data,
        options: {
            responsive: true,
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: 'day'
                    }
                },
                y: {
                    beginAtZero: true
                }
            },
            plugins: {
                title: {
                    display: true,
                    text: 'Analytics'
                }
            }
        }
    });
});
```

File: static/css/main.css
Required Change: Style the graph container.

```css
#analyticsChartContainer {
    width: 100%;
    height: 400px;
    border: 1px solid #ccc;
    border-radius: 5px;
    overflow: hidden;
}
```

File: feed.html
Required Change: Add the canvas element for the graph.

```html
<div id="analyticsChartContainer">
    <canvas id="analyticsChart"></canvas>
</div>
```

File: base.html
Required Change: Add the static files to the template.

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}My Django Project{% endblock %}</title>
    {% load static %}
    <link rel="stylesheet" href="{% static 'css/main.css' %}">
</head>
<body>
    {% block content %}
    {% endblock %}
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="{% static 'js/main.js' %}"></script>
</body>
</html>
```

Note: The 'comments_data' variable should be passed from the views.py to the feed.html template using the context.