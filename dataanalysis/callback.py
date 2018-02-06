import datetime

import requests

from dataanalysis.printhook import log


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

        log("callback currently accepts classes",cls.callback_accepted_classes)

    def __init__(self,url):
        self.url=url

    def __repr__(self):
        return "[%s: %s]"%(self.__class__.__name__,self.url)

    def filter_callback(self,level,obj,message,data):
        if self.callback_accepted_classes is None:
            return True

        for accepted_class in self.callback_accepted_classes:
            try:
                if issubclass(obj.__class__, accepted_class):
                    return True
            except Exception as e:
                log("unable to filter",obj,obj.__class__,accepted_class)
                raise

        return False

    def process_callback(self,level,obj,message,data):
        if self.filter_callback(level,obj,message,data):
            return self.process_filtered(level,obj,message,data)

    def extract_data(self,obj):
        if obj._da_locally_complete is not None:
            return obj._da_locally_complete
        return {}

    def process_filtered(self,level,obj,message,data):
        if self.url is None:
            return

        if self.url.startswith("file://"):
            fn=self.url[len("file://"):]
            with open(fn,'a') as f:
                f.write(str(datetime.datetime.now())+" "+level+": "+" in "+str(obj)+" got "+message+"; "+repr(data)+"\n")

        elif self.url.startswith("http://"):
            params=dict(
                level=level,
                node=obj.get_signature(),
                message=message,
            )
            params.update(self.extract_data(obj))
            params['action']=data.get('state', 'progress')
            try:
                requests.get(self.url,
                             params=params)
            except requests.ConnectionError as e:
                log("callback failed:",e)
        else:
            raise Exception("unknown callback method",self.url)


default_callback_filter=Callback
