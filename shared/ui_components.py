"""
UI components and styling for ethPandaOps Analysis Dashboard
"""


def add_ethPandaOps_logo(fig):
    """Add ethPandaOps logo to a plotly figure."""
    # Add ethPandaOps logo using remote URL
    fig.add_layout_image(
        dict(
            source="https://ethpandaops.io/img/logo-slim.png",
            xref="paper", yref="paper",
            x=0.02, y=0.98,  # Top left position
            sizex=0.08, sizey=0.08,  # Small logo
            xanchor="left", yanchor="top",
            opacity=0.8
        )
    )
    return fig


def get_ethPandaOps_chart_config():
    """Get standard plotly chart configuration for ethPandaOps branding."""
    return {
        'displaylogo': False,  # Hide Plotly logo
        'modeBarButtonsToRemove': ['lasso2d', 'select2d'],  # Remove unnecessary tools
        'displayModeBar': True,  # Keep the toolbar visible
        'toImageButtonOptions': {
            'format': 'png',
            'filename': 'ethpandaops_chart',
            'height': None,
            'width': None,
            'scale': 2  # Higher quality image export
        }
    }


def apply_ethPandaOps_styling():
    """Deprecated: Styling now handled at app level through Streamlit theming."""
    pass
