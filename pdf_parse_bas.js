[[ERROR_PDF]] = 0;

const fs = require("fs");
const pdf = require("pdf-parse");



let dataBuffer = fs.readFileSync([[FILE_PDF]]);

await(new Promise((resolve, reject) => {

    pdf(dataBuffer).then(function (data) {
        [[PDF_TXT]] = (data.text);
        resolve()
    }).catch(function(e){
        [[ERROR_PDF]] = 1;
        resolve()
    })

}));