// Analytics.js - Handles rendering of user interaction analytics on the feed page

document.addEventListener('DOMContentLoaded', function() {
  const analyticsContainer = document.getElementById('analytics-container');
  
  if (!analyticsContainer) {
    console.error('Analytics container not found');
    return;
  }
  
  // Create the analytics section
  analyticsContainer.innerHTML = `
    <div class="analytics-section">
      <h3>Your Post Interactions (Last 10 Days)</h3>
      <div id="analyticsError" class="alert alert-info" style="display: none;">
        Loading interaction data...
      </div>
      <div class="analytics-charts">
        <div class="chart-container">
          <h4>Daily Comments</h4>
          <canvas id="commentsChart"></canvas>
        </div>
      </div>
    </div>
  `;
  
  // Fetch comment interaction data
  fetchAnalyticsData();
});

function fetchAnalyticsData() {
  // In a real application, this would be an API endpoint
  // For this implementation, we'll use sample data
  
  const errorElement = document.getElementById('analyticsError');
  
  try {
    // Generate data for the last 10 days
    const data = generateSampleData();
    renderCommentsChart(data);
    
    // Hide the loading/error message
    if (errorElement) {
      errorElement.style.display = 'none';
    }
  } catch (error) {
    console.error('Error rendering analytics:', error);
    if (errorElement) {
      errorElement.textContent = 'Could not load analytics data.';
      errorElement.style.display = 'block';
      errorElement.className = 'alert alert-danger';
    }
  }
}

function generateSampleData() {
  const data = [];
  const today = new Date();
  
  // Generate data for the last 10 days
  for (let i = 9; i >= 0; i--) {
    const date = new Date();
    date.setDate(today.getDate() - i);
    
    data.push({
      date: date.toISOString().split('T')[0],
      comments: Math.floor(Math.random() * 15) // Random number of comments (0-15)
    });
  }
  
  return data;
}

function renderCommentsChart(data) {
  const ctx = document.getElementById('commentsChart');
  
  if (!ctx) {
    console.error('Chart canvas not found');
    return;
  }
  
  const labels = data.map(item => {
    const date = new Date(item.date);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  });
  
  const values = data.map(item => item.comments);
  
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'Comments',
        data: values,
        backgroundColor: 'rgba(54, 162, 235, 0.6)',
        borderColor: 'rgba(54, 162, 235, 1)',
        borderWidth: 1
      }]
    },
    options: {
      responsive: true,
      scales: {
        y: {
          beginAtZero: true,
          ticks: {
            precision: 0 // Only show integers
          }
        }
      },
      plugins: {
        tooltip: {
          callbacks: {
            title: function(tooltipItems) {
              return tooltipItems[0].label;
            },
            label: function(context) {
              return `Comments: ${context.parsed.y}`;
            }
          }
        }
      }
    }
  });
} 