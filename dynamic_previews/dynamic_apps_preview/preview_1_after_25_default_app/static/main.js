static/js/main.js:

```javascript
document.addEventListener('DOMContentLoaded', function() {
    const calendarEl = document.getElementById('calendar');

    const calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'dayGridMonth',
        events: '/api/posts/',
        eventColor: '#378006',
    });

    calendar.render();

    // Add a new function to handle the filter form submission and display the posts from the past week.
    document.querySelector('#filter-form').addEventListener('submit', function(e) {
        e.preventDefault();
        const formData = new FormData(this);
        const weekAgo = new Date();
        weekAgo.setDate(weekAgo.getDate() - 7);
        const filterData = {
            start_date: weekAgo.toISOString().split('T')[0],
            end_date: new Date().toISOString().split('T')[0],
        };
        for (let [key, value] of formData.entries()) {
            filterData[key] = value;
        }
        fetch('/api/posts/filter/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(filterData),
        })
        .then(response => response.json())
        .then(data => {
            const events = data.map(post => {
                return {
                    title: post.title,
                    start: post.created_at,
                    end: post.created_at,
                    id: post.id,
                    url: `/posts/${post.id}/`,
                };
            });
            calendar.addEventSource(events);
            calendar.refetchEvents();
        });
    });

    // Integrate Chart.js with 'comments_data'
    if (comments_data) {
        const ctx = document.getElementById('analyticsChart').getContext('2d');
        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: comments_data.dates,
                datasets: [{
                    label: 'Number of Comments',
                    data: comments_data.counts,
                    backgroundColor: [
                        'rgba(255, 99, 132, 0.2)',
                        'rgba(54, 162, 235, 0.2)',
                        'rgba(255, 206, 86, 0.2)',
                        'rgba(75, 192, 192, 0.2)',
                        'rgba(153, 102, 255, 0.2)',
                        'rgba(255, 159, 64, 0.2)'
                    ],
                    borderColor: [
                        'rgba(255, 99, 132, 1)',
                        'rgba(54, 162, 235, 1)',
                        'rgba(255, 206, 86, 1)',
                        'rgba(75, 192, 192, 1)',
                        'rgba(153, 102, 255, 1)',
                        'rgba(255, 159, 64, 1)'
                    ],
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
    }
});
```

File: static/css/style.css
Required Change: Style elements as specified (e.g., graph container).

static/css/style.css:

```css
/* Add styles for the graph container */
#analyticsChartContainer {
    width: 100%;
    max-width: 800px;
    margin: 0 auto;
}
```