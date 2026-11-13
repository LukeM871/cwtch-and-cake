// CloudFront Function (viewer request) for the website's pages. Not used for /api/*.
//   /menu/          -> served from /menu/index.html in the private S3 bucket
//   /menu           -> 301 to /menu/ (keeping any ?query), so every page has one address
//   /css/site.css   -> untouched (anything whose last part has a dot is a file)
function handler(event) {
  var request = event.request;
  var uri = request.uri;

  if (uri.endsWith('/')) {
    request.uri = uri + 'index.html';
    return request;
  }

  var last = uri.substring(uri.lastIndexOf('/') + 1);
  if (last.indexOf('.') !== -1) {
    return request;
  }

  var parts = [];
  var query = request.querystring;
  for (var key in query) {
    var value = query[key];
    if (value.multiValue) {
      for (var i = 0; i < value.multiValue.length; i++) {
        parts.push(key + '=' + value.multiValue[i].value);
      }
    } else {
      parts.push(value.value === '' ? key : key + '=' + value.value);
    }
  }
  return {
    statusCode: 301,
    statusDescription: 'Moved Permanently',
    headers: {
      location: { value: uri + '/' + (parts.length ? '?' + parts.join('&') : '') },
      'cache-control': { value: 'max-age=3600' }
    }
  };
}
