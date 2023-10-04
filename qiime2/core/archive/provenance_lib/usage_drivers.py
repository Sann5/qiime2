# ----------------------------------------------------------------------------
# Copyright (c) 2016-2023, QIIME 2 development team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file LICENSE, distributed with this software.
# ----------------------------------------------------------------------------
from datetime import datetime
from importlib.metadata import metadata
import pkg_resources
import textwrap
from typing import Any, Callable, List

from .parse import ProvDAG

from qiime2.sdk import Action
from qiime2.plugins import ArtifactAPIUsage
from qiime2.sdk.usage import (
    Usage, UsageVariable, UsageInputs, UsageOutputs
)


def build_header(
    shebang: str = '',
    boundary: str = '',
    copyright: str = '',
    extra_text: List[str] = []
) -> List[str]:
    '''
    Constructs the header contents for a replay script.

    Parameters
    ----------
    shebang : str
        The shebang line to add to the rendered script, if any.
    boundary : str
        The visual boundary to add to the rendred script, if any.
    copyright : str
        The copyright notice to add to the rendered script, if any.
    extra_text : list of str
        Extra lines of text to add to the header in the rendered script,
        if any.

    Returns
    -------
    list of str
        The constructed header lines.
    '''
    qiime2_md = metadata('qiime2')
    vzn = qiime2_md['Version']
    ts = datetime.now()
    header = []

    if shebang:
        header.append(shebang)

    if boundary:
        header.append(boundary)

    header.extend([
        f'# Auto-generated by qiime2 v.{vzn} at '
        f'{ts.strftime("%I:%M:%S %p")} on {ts.strftime("%d %b, %Y")}',
    ])

    if copyright:
        header.extend(copyright)

    header.append(
        '# For User Support, post to the QIIME2 Forum at '
        'https://forum.qiime2.org.'
    )

    if extra_text:
        header.extend(extra_text)
    if boundary:
        header.append(boundary)
    return header


def build_footer(dag: ProvDAG, boundary: str) -> List[str]:
    '''
    Constructs the footer contents for a replay script.

    Parameters
    ----------
    dag : ProvDAG
        The ProvDAG object representing the input artifact(s).
    boundary : str
        The visual boundary demarcating the footer.

    Returns
    -------
    list of str
        The constructed footer lines as a list of strings.
    '''
    footer = []
    pairs = []
    uuids = sorted(dag._parsed_artifact_uuids)
    # two UUIDs fit on a line
    for idx in range(0, u_len := len(uuids), 2):
        if idx == u_len - 1:
            pairs.append(f'# {uuids[idx]}')
        else:
            pairs.append(f'# {uuids[idx]} \t {uuids[idx + 1]}')

    footer.append(boundary)
    footer.append(
        '# The following QIIME 2 Results were parsed to produce this script:'
    )
    footer.extend(pairs)
    footer.append(boundary)
    footer.append('')
    return footer


class ReplayPythonUsage(ArtifactAPIUsage):
    shebang = '#!/usr/bin/env python'
    header_boundary = '# ' + ('-' * 77)
    copyright = pkg_resources.resource_string(
        'qiime2.core.archive.provenance_lib',
        'assets/copyright_note.txt'
    ).decode('utf-8').split('\n')
    how_to = pkg_resources.resource_string(
        'qiime2.core.archive.provenance_lib',
        'assets/python_howto.txt'
    ).decode('utf-8').split('\n')

    def __init__(
        self,
        enable_assertions: bool = False,
        action_collection_size: int = 2
    ):
        '''
        Identical to parent, but with smaller default action_collection_size.

        Parameters
        ----------
        enable_assertions : bool
            Whether to render has-line-matching and output type assertions.
        action_collection_size : int
            The maximum number of outputs returned by an action above which
            results are grouped into and destructured from a single variable.
        '''
        super().__init__()
        self.enable_assertions = enable_assertions
        self.action_collection_size = action_collection_size
        self._reset_state(reset_global_imports=True)

    def _reset_state(self, reset_global_imports=False):
        '''
        Clears all state associated with the usage driver, excepting global
        imports by default.

        Parameters
        ----------
        resest_global_imports : bool
            Whether to reset self.global_imports to an empty set.
        '''
        self.local_imports = set()
        self.header = []
        self.recorder = []
        self.footer = []
        self.init_data_refs = dict()
        if reset_global_imports:
            self.global_imports = set()

    def _template_action(
        self, action: Action, input_opts: UsageInputs, variables: UsageOutputs
    ):
        '''
        Templates the artifact api python code for the action `action`.

        Extends the parent method to:
        - accommodate action signatures that may differ between those found in
          provenance and those accessible in the currently executing
          environment
        - render artifact api code that saves the results to disk.

        Parameters
        ----------
        action : Action
            The qiime2 Action object.
        input_opts : UsageInputs
            The UsageInputs mapping for the action.
        variables : UsageOutputs
            The UsageOutputs object for the action.
        '''
        action_f = action.get_action()
        if (
            len(variables) > self.action_collection_size
            or len(action_f.signature.outputs) > 5
        ):
            output_vars = 'action_results'
        else:
            output_vars = self._template_outputs(action, variables)

        plugin_id = action.plugin_id
        action_id = action.action_id
        lines = [
            f'{output_vars} = {plugin_id}_actions.{action_id}('
        ]

        all_inputs = (list(action_f.signature.inputs.keys()) +
                      list(action_f.signature.parameters.keys()))
        for k, v in input_opts.items():
            line = ''
            if k not in all_inputs:
                line = self.INDENT + (
                    '# FIXME: The following parameter name was not found in '
                    'your current\n    # QIIME 2 environment. This may occur '
                    'when the plugin version you have\n    # installed does '
                    'not match the version used in the original analysis.\n '
                    ' # Please see the docs and correct the parameter name '
                    'before running.\n'
                )
            line += self._template_input(k, v)
            lines.append(line)

        lines.append(')')

        if (
            len(variables) > self.action_collection_size
            or len(action.get_action().signature.outputs) > 5
        ):
            for k, v in variables._asdict().items():
                interface_name = v.to_interface_name()
                lines.append('%s = action_results.%s' % (interface_name, k))

        lines.append(
            '# SAVE: comment out the following with \'# \' to skip saving '
            'Results to disk'
        )
        for k, v in variables._asdict().items():
            interface_name = v.to_interface_name()
            lines.append(
                '%s.save(\'%s\')' % (interface_name, interface_name,))

        lines.append('')
        self._add(lines)

    def _template_outputs(
        self, action: Action, variables: UsageOutputs
    ) -> str:
        '''
        Extends the parent method to allow the replay an action when a
        ProvDAG doesn't have a record of all outputs from an action. These
        unknown outputs are given the conventional '_' variable name.

        Parameters
        ----------
        action : Action
            The Action object associated with the output variables.
        variables : UsageOutputs
            The UsageOutputs object associated with the action.

        Returns
        -------
        str
            The templated output variables names as a comma-separated string.
        '''
        output_vars = []
        action_f = action.get_action()

        # need to coax the outputs into the correct order for unpacking
        for output in action_f.signature.outputs:
            try:
                variable = getattr(variables, output)
                output_vars.append(str(variable.to_interface_name()))
            except AttributeError:
                output_vars.append('_')

        if len(output_vars) == 1:
            output_vars.append('')

        return ', '.join(output_vars).strip()

    def init_metadata(
        self, name: str, factory: Callable, dumped_md_fn: str = ''
    ) -> UsageVariable:
        '''
        Renders the loading of Metadata from disk.

        Parameters
        ----------
        name : str
            The name of the created and returned UsageVariable.
        factory : Callable
            The factory responsible for constructing the metadata
            UsageVariable.
        dumped_md_fn : str
            Optional. The filename of the dumped metadata.

        Returns
        -------
        UsageVariable
            The UsageVariable of var_type metadata corresponding to the
            loaded metadata.
        '''
        var = super().init_metadata(name, factory)
        self._update_imports(from_='qiime2', import_='Metadata')
        input_fp = var.to_interface_name()
        if dumped_md_fn:
            lines = [f'{input_fp} = Metadata.load("{dumped_md_fn}.tsv")']
        else:
            self.comment(
                'NOTE: You may substitute already-loaded Metadata for the '
                'following, or cast a pandas.DataFrame to Metadata as needed.'
            )
            lines = [f'{input_fp} = Metadata.load(<your metadata filepath>)']

        self._add(lines)
        return var

    def import_from_format(
        self,
        name: str,
        semantic_type: str,
        variable: UsageVariable,
        view_type: Any = None
    ):
        '''
        Extends the parent method to:
        - use '<your data here>' instead of import_fp for the import filepath
        - render artifact api code that saves the result to disk.

        Parameters
        ----------
        name : str
            The name of the UsageVariable `variable`.
        semantic_type : str
            The semantic type of the UsageVariable `variable`.
        variable : UsageVariable
            The usage variable object.
        view_type : str or some format
            The view type to use for importing.

        Returns
        -------
        UsageVariable
            The imported artifact UsageVariable.
        '''
        imported_var = Usage.import_from_format(
            self, name, semantic_type, variable, view_type=view_type
        )

        interface_name = imported_var.to_interface_name()
        import_fp = self.repr_raw_variable_name('<your data here>')

        lines = [
            '%s = Artifact.import_data(' % (interface_name,),
            self.INDENT + '%r,' % (semantic_type,),
            self.INDENT + '%r,' % (import_fp,),
        ]

        if view_type is not None:
            if type(view_type) is not str:
                # Show users where these formats come from when used in the
                # Python API to make things less 'magical'.
                import_path = super()._canonical_module(view_type)
                view_type = view_type.__name__
                if import_path is not None:
                    self._update_imports(from_=import_path,
                                         import_=view_type)
                else:
                    # May be in scope already, but something is quite wrong at
                    # this point, so assume the plugin_manager is sufficiently
                    # informed.
                    view_type = repr(view_type)
            else:
                view_type = repr(view_type)

            lines.append(self.INDENT + '%s,' % (view_type,))

        lines.extend([
            ')',
            '# SAVE: comment out the following with \'# \' to skip saving this'
            ' Result to disk',
            '%s.save(\'%s\')' % (interface_name, interface_name,),
            ''
        ])

        self._update_imports(from_='qiime2', import_='Artifact')
        self._add(lines)

        return imported_var

    class repr_raw_variable_name:
        # allows us to repr col name without enclosing quotes
        # (as in qiime2.qiime2.plugins.ArtifactAPIUsageVariable)
        def __init__(self, value):
            self.value = value

        def __repr__(self):
            return self.value

    def comment(self, line: str):
        '''
        Communicate that a comment should be rendered.

        Parameters
        ----------
        line : str
            The comment to be rendered.
        '''
        LINE_LEN = 79
        lines = textwrap.wrap(
            line,
            LINE_LEN,
            break_long_words=False,
            initial_indent='# ',
            subsequent_indent='# '
        )
        lines.append('')
        self._add(lines)

    def render(self, flush: bool = False) -> str:
        '''
        Return a newline-seperated string of Artifact API python code.

        Parameters
        ----------
        flush : bool
            Whether to 'flush' the current code. Importantly, this will clear
            the top-line imports for future invocations.

        Returns
        -------
        str
            The rendered string of python code.
        '''
        sorted_imps = sorted(self.local_imports)
        if self.header:
            self.header = self.header + ['']
        if self.footer:
            self.footer = [''] + self.footer
        if sorted_imps:
            sorted_imps = sorted_imps + ['']
        rendered = '\n'.join(
            self.header + sorted_imps + self.recorder + self.footer
        )
        if flush:
            self._reset_state()
        return rendered

    def build_header(self):
        '''Constructs a renderable header from its components.'''
        self.header.extend(build_header(
            self.shebang, self.header_boundary, self.copyright, self.how_to
        ))

    def build_footer(self, dag: ProvDAG):
        '''
        Constructs a renderable footer using the terminal uuids of a ProvDAG.
        '''
        self.footer.extend(build_footer(dag, self.header_boundary))