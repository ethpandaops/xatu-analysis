import matplotlib.pyplot as plt
import seaborn as sns
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from typing import Optional, List, Tuple

plt.style.use('seaborn-v0_8')
sns.set_palette("husl")


def create_time_series_plot(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    title: Optional[str] = None,
    interactive: bool = False,
    figsize: Tuple[int, int] = (12, 6),
) -> None:
    if interactive:
        fig = px.line(
            df,
            x=x_col,
            y=y_col,
            title=title or f"{y_col} over {x_col}",
        )
        fig.show()
    else:
        plt.figure(figsize=figsize)
        plt.plot(df[x_col], df[y_col])
        plt.title(title or f"{y_col} over {x_col}")
        plt.xlabel(x_col)
        plt.ylabel(y_col)
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.show()


def create_histogram(
    df: pd.DataFrame,
    col: str,
    bins: int = 50,
    title: Optional[str] = None,
    interactive: bool = False,
    figsize: Tuple[int, int] = (10, 6),
) -> None:
    if interactive:
        fig = px.histogram(
            df,
            x=col,
            nbins=bins,
            title=title or f"Distribution of {col}",
        )
        fig.show()
    else:
        plt.figure(figsize=figsize)
        plt.hist(df[col], bins=bins, alpha=0.7, edgecolor='black')
        plt.title(title or f"Distribution of {col}")
        plt.xlabel(col)
        plt.ylabel("Frequency")
        plt.tight_layout()
        plt.show()


def create_scatter_plot(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    color_col: Optional[str] = None,
    title: Optional[str] = None,
    interactive: bool = False,
    figsize: Tuple[int, int] = (10, 8),
) -> None:
    if interactive:
        fig = px.scatter(
            df,
            x=x_col,
            y=y_col,
            color=color_col,
            title=title or f"{y_col} vs {x_col}",
        )
        fig.show()
    else:
        plt.figure(figsize=figsize)
        if color_col:
            scatter = plt.scatter(df[x_col], df[y_col], c=df[color_col], alpha=0.6)
            plt.colorbar(scatter, label=color_col)
        else:
            plt.scatter(df[x_col], df[y_col], alpha=0.6)
        
        plt.title(title or f"{y_col} vs {x_col}")
        plt.xlabel(x_col)
        plt.ylabel(y_col)
        plt.tight_layout()
        plt.show()
