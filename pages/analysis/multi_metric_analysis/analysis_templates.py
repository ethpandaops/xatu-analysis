"""
File-based analysis templates for performance analysis scenarios.

Templates are loaded from YAML files in the templates directory.
"""

import os
import yaml
from typing import Dict, Any, List, Optional
import streamlit as st


class AnalysisTemplate:
    """Template for analysis configuration."""
    
    def __init__(self, data: Dict[str, Any]):
        self.name = data.get('name', 'Unnamed Template')
        self.description = data.get('description', '')
        self.x_metric = data.get('x_metric', '')
        self.y_metrics = data.get('y_metrics', [])
        self.aggregation_level = data.get('aggregation_level', 'No Aggregation (Raw Data)')
        self.aggregation_function = data.get('aggregation_function', 'mean')
        self.enable_time_buckets = data.get('enable_time_buckets', False)
        self.enable_two_stage = data.get('enable_two_stage', False)
        self.first_stage_agg = data.get('first_stage_agg', 'mean')
        self.second_stage_agg = data.get('second_stage_agg', 'mean')
        self.show_trend_line = data.get('show_trend_line', True)
        self.show_attestation_deadline = data.get('show_attestation_deadline', False)
        self.start_y_from_zero = data.get('start_y_from_zero', True)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert template to configuration dictionary."""
        return {
            'name': self.name,
            'description': self.description,
            'x_metric': self.x_metric,
            'y_metrics': self.y_metrics,
            'aggregation_level': self.aggregation_level,
            'aggregation_function': self.aggregation_function,
            'enable_time_buckets': self.enable_time_buckets,
            'enable_two_stage': self.enable_two_stage,
            'first_stage_agg': self.first_stage_agg,
            'second_stage_agg': self.second_stage_agg,
            'show_trend_line': self.show_trend_line,
            'show_attestation_deadline': self.show_attestation_deadline,
            'start_y_from_zero': self.start_y_from_zero
        }


def get_templates_dir() -> str:
    """Get the templates directory path."""
    return os.path.join(os.path.dirname(__file__), 'templates')


def load_templates() -> Dict[str, AnalysisTemplate]:
    """Load all templates from the templates directory."""
    templates = {}
    templates_dir = get_templates_dir()
    
    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir)
        return templates
    
    for filename in os.listdir(templates_dir):
        if filename.endswith('.yaml') or filename.endswith('.yml'):
            filepath = os.path.join(templates_dir, filename)
            try:
                with open(filepath, 'r') as f:
                    data = yaml.safe_load(f)
                    if data:
                        template = AnalysisTemplate(data)
                        templates[template.name] = template
            except Exception as e:
                st.warning(f"Error loading template {filename}: {e}")
    
    return templates


def save_template(config: Dict[str, Any], name: str, description: str) -> bool:
    """Save a configuration as a new template."""
    templates_dir = get_templates_dir()
    
    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir)
    
    # Create filename from name (sanitize it)
    filename = name.lower().replace(' ', '_').replace('/', '_')
    filename = ''.join(c for c in filename if c.isalnum() or c == '_')
    filepath = os.path.join(templates_dir, f"{filename}.yaml")
    
    # Prepare template data
    template_data = {
        'name': name,
        'description': description,
        'x_metric': config.get('x_metric', ''),
        'y_metrics': config.get('y_metrics', []),
        'aggregation_level': config.get('aggregation_level', 'No Aggregation (Raw Data)'),
        'aggregation_function': config.get('aggregation_function', 'mean'),
        'enable_time_buckets': config.get('enable_time_buckets', False),
        'enable_two_stage': config.get('enable_two_stage', False),
        'first_stage_agg': config.get('first_stage_agg', 'mean'),
        'second_stage_agg': config.get('second_stage_agg', 'mean'),
        'show_trend_line': config.get('show_trend_line', True),
        'show_attestation_deadline': config.get('show_attestation_deadline', False),
        'start_y_from_zero': config.get('start_y_from_zero', True)
    }
    
    try:
        with open(filepath, 'w') as f:
            yaml.dump(template_data, f, default_flow_style=False, sort_keys=False)
        return True
    except Exception as e:
        st.error(f"Error saving template: {e}")
        return False


def get_template(name: str) -> Optional[AnalysisTemplate]:
    """Get a template by name."""
    templates = load_templates()
    return templates.get(name)


def get_template_names() -> List[str]:
    """Get list of available template names."""
    templates = load_templates()
    return list(templates.keys())


def get_default_template() -> str:
    """Get the default template name."""
    templates = get_template_names()
    if "Gas vs Block Propagation" in templates:
        return "Gas vs Block Propagation"
    return templates[0] if templates else ""