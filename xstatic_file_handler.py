import os.path
import tornado.web
from xstatic.main import XStatic

class XStaticFileHandler(tornado.web.StaticFileHandler):
    _cached_xstatic_data_dirs = {}

    def initialize(self, allowed_modules=None, **kwargs):
        if allowed_modules:
            self.allowed_modules = set(allowed_modules)
        else:
            self.allowed_modules = None
        self.prefix = prefix
        
        assert 'root' not in kwargs
        # XXX: Not wild on passing root=/ , because StaticFileHandler's own
        # validation will let this serve any file. If this subclass is working
        # correctly, that shouldn't be an issue, but...
        super(XStaticFileHandler).initialize(root="/")
        

    def parse_url_path(self, url_path):
        if '/' not in url_path:
            raise tornado.web.HTTPError(403, "XStatic module, not a file")
        if self.allowed_modules is not None:
            module_name = url_path.split('/', 1)[0]
            if module_name not in self.allowed_modules:
                raise tornado.web.HTTPError(403,
                        'Access to XStatic module %s denied', module_name)

        return super(XStaticFileHandler, self).parse_url_path(url_path)

    @classmethod
    def _get_xstatic_data_dir(cls, mod_name):
        try:
            return cls._cached_xstatic_data_dirs[mod_name]
        except KeyError:
            xsmod = getattr(__import__('xstatic.pkg', fromlist=[mod_name]), mod_name)
            data_dir = os.path.abspath(xsmod.BASE_DIR)
            if not data_dir.endswith(os.path.sep):
                # So joining ../datafoo will not be valid
                data_dir += os.path.sep
            cls._cached_xstatic_data_dirs[mod_name] = data_dir
            return data_dir

    @classmethod
    def get_absolute_path(cls, root, path):
        mod_name, path = path.split(os.path.sep, 1)
        root = cls._get_xstatic_data_dir(mod_name)
        abs_path = os.path.join(root, path)
        if not abs_path.startswith(root):
            raise tornado.web.HTTPError(403, 
                "Request for file outside XStatic package %s: %s", mod_name, path)
        
        return abs_path

def url_maker(prefix):
    def make_url(package, path): 
        return prefix + package + "/" + path
    return make_url