// Agent OS UI - vanilla JS
document.addEventListener('DOMContentLoaded', () => {
    // Pattern card selection
    document.querySelectorAll('.pattern-card').forEach(card => {
        card.addEventListener('click', () => {
            document.querySelectorAll('.pattern-card').forEach(c => c.classList.remove('active'));
            card.classList.add('active');
            const select = document.getElementById('pattern-select');
            if (select) select.value = card.dataset.pattern;
        });
    });

    // Pattern form
    const patternForm = document.getElementById('pattern-form');
    if (patternForm) {
        patternForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const result = document.getElementById('pattern-result');
            const pattern = document.getElementById('pattern-select').value;
            const task = document.getElementById('task-input').value;
            result.textContent = 'Running...';
            try {
                const response = await fetch('/api/v1/multi-agent/run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ pattern, task, config: {} }),
                });
                if (!response.ok) {
                    result.textContent = `Error: ${response.status} ${response.statusText}`;
                    return;
                }
                const data = await response.json();
                result.textContent = JSON.stringify(data, null, 2);
            } catch (err) {
                result.textContent = `Error: ${err.message}`;
            }
        });
    }
});
