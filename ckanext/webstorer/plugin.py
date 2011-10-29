from ckan import model
from ckan.plugins import SingletonPlugin, implements, IDomainObjectModification, \
    IResourceUrlChange, IConfigurable
from ckan.logic import get_action
from celery.execute import send_task
from ckan.lib.dictization.model_dictize import resource_dictize
import json
from datetime import datetime

class WebstorerPlugin(SingletonPlugin):
    """
    Registers to be notified whenever CKAN resources are created or their URLs change,
    and will create a new ckanext.webstorer celery task to put the resource in the webstore.
    """
    implements(IDomainObjectModification, inherit=True)
    implements(IResourceUrlChange)
    implements(IConfigurable)

    def configure(self, config):
        self.site_url = config.get('ckan.site_url')
        self.webstore_url = config.get('ckan.webstore_url')

    def notify(self, entity, operation=None):
        if not isinstance(entity, model.Resource):
            return
        
        if operation:
            if operation == model.DomainObjectOperation.new:
                self._create_webstorer_task(entity)
        else:
            # if operation is None, resource URL has been changed, as the
            # notify function in IResourceUrlChange only takes 1 parameter
            self._create_webstorer_task(entity)

    def _create_webstorer_task(self, resource):
        user = get_action('get_site_user')({'model': model,
                                            'ignore_auth': True,
                                            'defer_commit': True}, {})
        context = json.dumps({
            'site_url': self.site_url,
            'apikey': user.get('apikey'),
            'username': user.get('name'),
            'webstore_url': self.webstore_url
        })
        data = json.dumps(resource_dictize(resource, {'model': model}))
        webstorer_task = send_task("webstorer.upload", [context, data])

        # update the task_status table
        webstorer_task_status = {
            'entity_id': resource.id,
            'entity_type': u'resource',
            'task_type': u'webstorer',
            'key': u'celery_task_id',
            'value': webstorer_task.task_id,
            'last_updated': datetime.now().isoformat()
        }
        
        archiver_task_context = {
            'model': model, 
            'session': model.Session, 
            'user': user.get('name'),
            'defer_commit': True
        }
        
        get_action('task_status_update')(archiver_task_context, webstorer_task_status)
