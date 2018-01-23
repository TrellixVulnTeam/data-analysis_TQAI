from dataanalysis.printhook import log
import datetime
import requests


class CallbackHook(object):
    def __call__(self, *args,**kwargs):
        level, obj=args
        message=kwargs['message']

        for callback_url in obj.callbacks:
            callback_filter=default_callback_filter
            if isinstance(callback_url,tuple):
                callback_url,callback_filter_name=callback_url #
                callback_filter=globals()[callback_filter_name]

            callback_class=callback_filter
            log("callback class:",callback_class)
            callback=callback_class(callback_url)
            log("processing callback url", callback_url, callback)
            callback.process_callback(level=level,obj=obj,message=message,data=kwargs)


class Callback(object):
    callback_accepted_classes = None

    @classmethod
    def set_callback_accepted_classes(cls,classes):
        if cls.callback_accepted_classes is None:
            cls.callback_accepted_classes=[]

        for c in classes:
            if c not in cls.callback_accepted_classes:
                log("adding accepted class",c)
                cls.callback_accepted_classes.append(c)

    def __init__(self,url):
        self.url=url

    def __repr__(self):
        return "[%s: %s]"%(self.__class__.__name__,self.url)

    def filter_callback(self,level,obj,message,data):
        if self.callback_accepted_classes is None:
            return True

        for accepted_class in self.callback_accepted_classes:
            if issubclass(obj.__class__, accepted_class):
                return True

        return True

    def process_callback(self,level,obj,message,data):
        if self.filter_callback(level,obj,message,data):
            return self.process_filtered(level,obj,message,data)

    def process_filtered(self,level,obj,message,data):
        if self.url.startswith("file://"):
            fn=self.url[len("file://"):]
            with open(fn,'a') as f:
                f.write(str(datetime.datetime.now())+" "+level+": "+" in "+str(obj)+" got "+message+"; "+repr(data)+"\n")

        elif self.url.startswith("http://"):
            requests.get(self.url+"/"+data.get('state','progress'),
                         params=dict(
                             level=level,
                             node=obj.get_signature(),
                             message=message,
                         ))
        else:
            raise Exception("unknown callback method",self.url)


default_callback_filter=Callback
