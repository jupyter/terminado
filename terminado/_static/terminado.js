function make_terminal(element, options, ws_url) {
    var ws = new WebSocket(ws_url);
    var term = new Terminal({
      cols: options.cols,
      rows: options.rows,
      screenKeys: true,
      useStyle: true
    });
    ws.onopen = function(event) {
        ws.send(JSON.stringify(["set_size", size.rows, size.cols,
                                    window.innerHeight, window.innerWidth]));
        term.on('data', function(data) {
            ws.send(JSON.stringify(['stdin', data]));
        });
        
        term.on('title', function(title) {
            document.title = title;
        });
        
        term.open(document.body);
        
        ws.onmessage = function(event) {
            json_msg = JSON.parse(event.data);
            switch(json_msg[0]) {
                case "stdout":
                    term.write(json_msg[1]);
                    break;
                case "disconnect":
                    term.write("\r\n\r\n[CLOSED]\r\n");
                    break;
            }
        };
    };
    return {socket: ws, term: term};
}
