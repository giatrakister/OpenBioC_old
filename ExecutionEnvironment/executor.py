
import os
import json
import logging
import argparse 

from collections import defaultdict

logging.basicConfig(level=logging.DEBUG)

class OBC_Executor_Exception(Exception):
	'''
	'''
	pass

def detect_circles(graph, start, end):
    '''
    https://stackoverflow.com/questions/40833612/find-all-cycles-in-a-graph-implementation
    '''
    fringe = [(start, [])]
    while fringe:
        state, path = fringe.pop()
        if path and state == end:
            yield path
            continue
        for next_state in graph[state]:
            if next_state in path:
                continue
            fringe.append((next_state, path+[next_state]))


class Worfklow:
    '''
    '''

    WORKFLOW_TYPE = 'workflow'
    INPUT_TYPE = 'input'
    OUTPUT_TYPE = 'output'
    STEP_TYPE = 'step'
    TOOL_TYPE = 'tool'

    def __init__(self, workflow_filename):
        '''
        '''

        if not os.path.exists(workflow_filename):
            raise OBC_Executor_Exception(f'File {workflow_filename} does not exist')

        self.workflow_filename = workflow_filename
        self.parse_workflow_filename()

    def __str__(self,):
        '''
        '''
        return json.dumps(self.workflow, indent=4)

    def tool_bash_script_generator(self,):
        '''
        '''
        tool_installation_order = self.get_tool_installation_order()
        for tool in tool_installation_order:
            logging.info('Building installation bash commands for: {}'.format(tool['label']))
            yield tool


    def parse_workflow_filename(self, ):
        '''
        Parse and perform sanity tests
        '''

        with open(self.workflow_filename) as f:
            self.workflow = json.load(f)

        self.input_parameters = self.get_input_parameters()
        self.root_workflow = self.get_root_workflow()
        self.root_inputs_outputs = self.get_input_output_from_workflow(self.root_workflow)

        # Apply some integrity checks
        for node in self.node_iterator():
            # Every node has a type
            assert 'type' in node
            # Every node has a id
            assert 'id' in node
            # Every node has a belongto
            assert 'belongto' in node

            # Assert proper fields and types in belongto
            if not node['belongto'] is None:
                assert 'name' in node['belongto']
                assert 'edit' in node['belongto']
                assert type(node['belongto']['name']) is str
                assert type(node['belongto']['edit']) is int

        # Check that that there are not circular dependencies
        self.check_tool_dependencies_for_circles();

        # Check that all root input output are set
        self.input_parameter_values = {}
        for root_input_node in self.root_inputs_outputs['inputs']:
            logging.info('The following input values have been set:')
            for arg_input_name, arg_input_value in self.input_parameters.items():
                if arg_input_name == root_input_node['id']:
                    logging.info('  {}={}'.format(root_input_node['id'], arg_input_value))
                    self.input_parameter_values[root_input_node['id']] = {'value': arg_input_value, 'description': root_input_node['description']}
                    break
            else:
                #message = 'Input parameter: {} has not been set!'.format(root_input_node['id'])
                #raise OBC_Executor_Exception(message)
                local_input_parameter = input('Input parameter: {} has not been set. Enter value:'.format(root_input_node['id']))
                self.input_parameter_values[root_input_node['id']] = {'value': local_input_parameter, 'description': root_input_node['description']}

    def check_tool_dependencies_for_circles(self,):
        '''
        '''

        # Get all tools
        all_tools = [node for node in self.node_iterator() if self.is_tool(node)]

        # Contruct the tool graph
        graph = {self.get_tool_slash_id(tool): tool['dependencies'] for tool in all_tools}

        for tool_id in graph.keys():
            circles = detect_circles(graph, tool_id, tool_id)
            try:
                circle = next(circles)
            except StopIteration as e:
                pass # This is supposed to happen
            else:
                message = 'Found circular tool dependency!'
                message += '\n' + ' --> '.join(circle)
                raise OBC_Executor_Exception(message)

    def get_tool_bash_commands(self, tool):
        '''
        '''

        # Add Bash commands
        ret =  '### BASH COMMANDS FOR TOOL: {}\n'.format(tool['label'])
        ret += tool['installation_commands'] + '\n'
        ret += '### END OF {}\n'.format(tool['label'])

        ret += '\n'
        ret += '### SETTING TOOL VARIABLES FOR: {}\n'.format(tool['label'])
        for tool_variable in tool['variables']:
            ret += '{}="{}" # {} \n'.format(tool_variable['name'], tool_variable['value'], tool_variable['description'])
        ret += '### END OF SETTING TOOL VARIABLES FOR: {}\n\n'.format(tool['label'])

        return ret


    def get_input_bash_commands(self,):
        '''
        '''
        ret = '### SET ROOT WORKFLOW INPUT PARAMETERS\n'
        for variable, data in self.input_parameter_values.items():
            ret += '{}="{}" #  {}\n'.format(variable, data['value'], data['description'])
        ret += '### END OF SET ROOT WORKFLOW INPUT PARAMETERS'

        return ret

    def get_step_bash_commands(self, ):
        '''
        TODO: CREATE AN ORDERING ACCORDING TO WORKFLOWS!
        '''
        ret = '### SETTING BASH FUNCTIONS FOR STEPS\n\n'
        for a_node in self.node_iterator():
            if not self.is_step(a_node):
                continue

            ret += '# STEP: {}\n'.format(a_node['id'])
            ret += '{} () {{\n'.format(a_node['id'])
            ret += a_node['bash'] + '\n'
            ret += '}\n'

        ret += '### END OF SETTING BASH FUNCTIONS FOR STEPS\n'

        return ret


    def get_tool_slash_id(self, tool):
        '''
        '''
        return '/'.join([tool['name'], tool['version'], str(tool['edit'])])

    def get_tool_installation_order(self, ):
        '''
        Get a list of tools in dependency order.
        '''

        def has_dependency(tool, list_of_tools):
            '''
            Checks if the tool has all its dependencies on the list of tools
            '''

            all_dependencies = [self.get_tool_slash_id(t) for t in list_of_tools]
            return all(t in all_dependencies for t in tool['dependencies'])


        ret = []

        # Get all tools
        all_tools = [a_node for a_node in self.node_iterator() if self.is_tool(a_node)]

        # Get all tools that have dependencies 
        dependencies_notok = []

        for tool in all_tools:
            if tool['dependencies']:
                dependencies_notok.append(tool)
            else:
                ret.append(tool)

        steps = 0
        while True:

            # If all dependencies have been resolved, break
            if not dependencies_notok:
                break

            steps += 1

            current_notok = []
            found_on_this_round = []
            for tool in dependencies_notok:
                if has_dependency(tool, ret):
                    found_on_this_round.append(tool)
                else:
                    current_notok.append(tool)

            ret.extend(found_on_this_round)
            dependencies_notok = current_notok
	
        return ret	


    def get_input_parameters(self, ):
        '''
        '''

        return self.workflow.get('arguments', [])

    def node_iterator(self,):
        '''
        '''
        for node in self.workflow['workflow']['elements']['nodes']:
            yield node['data']

    def get_root_workflow(self,):
        '''
        '''

        ret = None

        for node in self.node_iterator():
            if node.get('belongto', None) is None:
                if not ret is None:
                    raise OBC_Executor_Exception('Integrity Error: Found more than one root workflow')

                ret = node

        if ret is None:
            raise OBC_Executor_Exception('Failed to locate root worfklow')

        return ret

    def node_2_str(self, node):
        '''
        '''
        return json.dumps(node, indent=4)


    def is_input_output(self, node):
        '''
        '''
        return node['type'] in [self.INPUT_TYPE, self.OUTPUT_TYPE]

    def is_step(self, node):
        '''
        '''
        return node['type'] == self.STEP_TYPE

    def is_tool(self, node):
        '''
        '''
        return node['type'] == self.TOOL_TYPE


    def belongto(self, node):
        '''
        '''
        if node['belongto'] is None:
            return None

        return node['belongto']['name'] + '__' + str(node['belongto']['edit'])


    def get_input_output_from_workflow(self, node):
        '''
        '''

        if not node['type'] == self.WORKFLOW_TYPE:
            message = f'Cannot get input/ouputs from a no-network node \nNode: \n{self.node_2_str(node)}'
            raise OBC_Executor_Exception(message)

        ret = {'inputs': [], 'outputs': []}

        for a_node in self.node_iterator(): 
            if self.is_input_output(a_node) and self.belongto(a_node) == node['id']:
                ret[a_node['type'] + 's'].append(a_node)

        return ret

    def get_steps_from_workflow(self, node):
        '''
        '''
        if not node['type'] == self.WORKFLOW_TYPE:
            message = f'Cannot get steps from a no-network node \nNode: \n{self.node_2_str(node)}'
            raise OBC_Executor_Exception(message)

        ret = []
        for a_node in self.node_iterator():
            if self.is_step(a_node) and self.belongto(a_node) == node['id']:
                ret.append(a_node)

        return ret

class BaseExecutor():
    '''
    '''
    def __init__(self, workflow):
        if not isinstance(workflow, Worfklow):
            raise OBC_Executor_Exception('workflow Unknown ')
        self.workflow = workflow



class LocalExecutor(BaseExecutor):
    '''
    Creates a unique BIG script!
    '''

    def build(self, output_filename):
        with open(output_filename, 'w') as f:
            # INSTALLATION TOOL BASH
            for tool in self.workflow.tool_bash_script_generator():
                f.write(self.workflow.get_tool_bash_commands(tool))

            # INPUT PARAMETERS BASH
            f.write(self.workflow.get_input_bash_commands())

            # STEP FUNCTIONS BASH
            f.write(self.workflow.get_step_bash_commands())

        logging.info(f'Created file: {output_filename}')



class DockerExecutor(BaseExecutor):
    '''
    '''
    pass

class AmazonExecutor(BaseExecutor):
    '''
    '''
    pass

if __name__ == '__main__':
    '''

    '''
    parser = argparse.ArgumentParser(description='OpenBio-C worfklow execute-or')

    parser.add_argument('-W', '--workflow', dest='workflow_filename', help='JSON filename of the workflow to run', required=True)

    args = parser.parse_args()


    w = Worfklow(args.workflow_filename)
    #print (w.root_inputs_outputs)
    #print (w)
    #w.get_tool_installation_order()
    #list(w.tool_bash_script_generator())

    le = LocalExecutor(w)
    le.build(output_filename='script.sh')

	


