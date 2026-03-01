
const fs = require("fs");
const pdfParse = require("pdf-parse");

const filePath = process.argv[2];
const maxPages = parseInt(process.argv[3]) || 5;

const buf = fs.readFileSync(filePath);

const opts = {
    max: maxPages  // pdf-parse: max pages
};

pdfParse(buf, opts)
    .then(data => {
        // output as JSON
        process.stdout.write(JSON.stringify({
            ok: true,
            text: data.text,
            numpages: data.numpages,
            info: data.info || {}
        }));
    })
    .catch(err => {
        process.stdout.write(JSON.stringify({
            ok: false,
            error: err.message || String(err)
        }));
    });
