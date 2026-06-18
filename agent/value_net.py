"""Small MLP value function for cabt feature vectors."""

import torch
import torch.nn as nn


class ValueNet(nn.Module):
    """
    Input: feature vector.
    Output: win probability scalar, sigmoid-applied in [0, 1].
    """

    def __init__(self, input_dim: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)
