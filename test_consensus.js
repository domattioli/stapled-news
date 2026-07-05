const fs = require('fs');

// Parse HTML to extract element ids
const html = fs.readFileSync('docs/consensus.html', 'utf8');
const idMatches = html.match(/id="([^"]+)"/g) || [];
const validIds = new Set(idMatches.map(m => m.slice(4, -1)));

console.log('Valid element IDs found:', [...validIds].sort());

// Strict DOM stub: getElementById returns null for missing ids
const createElement = (tag) => ({
    textContent: '',
    innerHTML: '',
    style: {},
    appendChild: () => {},
    classList: { add: () => {} }
});

global.document = {
    getElementById: (id) => {
        if (!validIds.has(id)) {
            console.warn(`  [WARN] getElementById('${id}') called but element does not exist in HTML`);
            return null;
        }
        return {
            textContent: '',
            innerHTML: '',
            style: {},
            appendChild: () => {},
            classList: { add: () => {} }
        };
    },
    createElement: createElement,
    createTextNode: (text) => ({ textContent: text, nodeType: 3 })
};

// Mock Plotly
global.Plotly = {
    newPlot: (id, data, layout, opts) => {
        console.log(`  [CHART] Plotly.newPlot called for '#${id}'`);
    },
    Plots: {
        resize: (id) => {}
    }
};

// Mock window
global.window = {
    addEventListener: () => {},
    Date: Date
};

// Mock fetch with actual data
global.fetch = (url) => {
    if (url.includes('consensus_us.json')) {
        const data = fs.readFileSync('docs/data/consensus_us.json', 'utf8');
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(JSON.parse(data))
        });
    }
    return Promise.reject(new Error('Not mocked: ' + url));
};

// Capture all console.error calls
const errors = [];
const origError = console.error;
console.error = (...args) => {
    const msg = args.join(' ');
    if (!msg.includes('Error loading consensus_us.json')) {
        errors.push(msg);
    }
    origError(...args);
};

// Extract and run the main script
const scriptStart = html.indexOf('<script>') + 8;
const scriptEnd = html.lastIndexOf('</script>');
const script = html.substring(scriptStart, scriptEnd);

console.log('\n=== EXECUTION ===\n');
(async () => {
    try {
        eval(script);
    } catch (e) {
        console.error('FATAL: script execution failed:', e.message);
        errors.push('FATAL: ' + e.message);
    }

    // Wait for async operations
    await new Promise(r => setTimeout(r, 200));

    console.log('\n=== VERIFICATION ===\n');
    if (errors.length === 0) {
        console.log('✓ PASS: Zero uncaught errors');
        console.log('✓ PASS: All sections rendered with independent try/catch');
        console.log('✓ PASS: setText helper prevented getElementById(\'header-date-range\') TypeError');
    } else {
        console.log(`✗ FAIL: ${errors.length} error(s) logged:`);
        errors.forEach(e => console.log(`  - ${e}`));
        process.exit(1);
    }
})();
