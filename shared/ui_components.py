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


def apply_ethPandaOps_styling():
    """Deprecated: Styling now handled at app level through Streamlit theming."""
    pass
