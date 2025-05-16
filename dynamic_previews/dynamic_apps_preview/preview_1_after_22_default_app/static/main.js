```javascript
document.addEventListener('DOMContentLoaded', function() {
    var ctx = document.getElementById('analyticsChart').getContext('2d');
    var commentsData = {
        dates: ['2022-01-01', '2022-01-02', '2022-01-03', '2022-01-04', '2022-01-05'],
        counts: [10, 20, 15, 30, 25]
    };

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: commentsData.dates,
            datasets: [{
                label: 'Number of Comments',
                data: commentsData.counts,
                backgroundColor: 'rgba(75, 192, 192, 0.2)',
                borderColor: 'rgba(75, 192, 192, 1)',
                borderWidth: 1
            }]
        },
        options: {
            scales: {
                y: {
                    beginAtZero: true
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
    max-width: 800px;
    margin: 0 auto;
    padding: 20px;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}

#analyticsChart {
    width: 100%;
    height: 400px;
}
```

File: templates/base.html
Required Change: Load the static files.

```html
{% load static %}
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}My Django Project{% endblock %}</title>
    <link rel="stylesheet" href="{% static 'css/main.css' %}">
</head>
<body>
    <div id="analyticsChartContainer">
        <canvas id="analyticsChart"></canvas>
    </div>
    <script src="{% static 'js/main.js' %}"></script>
</body>
</html>
```