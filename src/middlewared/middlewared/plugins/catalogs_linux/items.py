import itertools
import markdown
import os
import yaml

from middlewared.schema import Str
from middlewared.service import accepts, CallError, private, Service


class CatalogService(Service):

    @accepts(Str('label'))
    def items(self, label):
        catalog = self.middleware.call_sync('catalog.get_instance', label)
        if not os.path.exists(catalog['location']):
            if not self.middleware.call_sync('catalog.update_git_repository', catalog):
                raise CallError(f'Unable to clone "{label}" catalog. Please refer to logs.')

        trains = {'charts': {}, 'test': {}}
        for train in filter(lambda c: os.path.exists(os.path.join(catalog['location'], c)), trains):
            category_path = os.path.join(catalog['location'], train)
            for item in filter(lambda p: os.path.isdir(os.path.join(category_path, p)), os.listdir(category_path)):
                item_location = os.path.join(category_path, item)
                trains[train][item] = {
                    'name': item,
                    'location': item_location,
                    **self.item_details(item_location)
                }

        return trains

    @private
    def item_details(self, item_path):
        # TODO: Discuss how we should map icon file
        # TODO: Add min/max TN version
        # Each directory under item path represents a version of the item and we need to retrieve details
        # for each version available under the item
        item_data = {'versions': {}}
        with open(os.path.join(item_path, 'item.yaml'), 'r') as f:
            item_data.update(yaml.load(f.read()))

        for version in filter(lambda p: os.path.isdir(os.path.join(item_path, p)), os.listdir(item_path)):
            item_data['versions'][version] = self.item_version_details(os.path.join(item_path, version))
        return item_data

    @private
    def item_version_details(self, version_path):
        version_data = {'location': version_path}
        for key, filename, parser in (
            ('values', 'values.yaml', yaml.load),
            ('questions', 'questions.yaml', yaml.load),
            ('app_readme', 'app-readme.md', markdown.markdown),
            ('detailed_readme', 'README.md', markdown.markdown),
        ):
            with open(os.path.join(version_path, filename), 'r') as f:
                version_data[key] = parser(f.read())

        # We will normalise questions now so that if they have any references, we render them accordingly
        # like a field referring to available interfaces on the system
        self.normalise_questions(version_data['questions'])

        return version_data

    @private
    def normalise_questions(self, questions):
        for question in questions:
            self._normalise_question(question)

    def _normalise_question(self, question):
        schema = question['schema']
        for attr in itertools.chain(
            *[d.get(k, []) for d, k in zip((schema, schema, question), ('attrs', 'items', 'subquestions'))]
        ):
            self._normalise_question(attr)

        if '$ref' not in question['schema']:
            return

        data = {}
        for ref in question['schema']['$ref']:
            if ref == 'definitions/interfaces':
                data['enum'] = [d['id'] for d in self.middleware.call_sync('interface.query')]

        question['schema'].update(data)