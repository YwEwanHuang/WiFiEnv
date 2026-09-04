"""Keras 3 compatibility shim for legacy Project_3 code.

Must be imported before any Project_3 module that uses:
    Adam(lr=...)          (Keras 2) → Keras 3 requires learning_rate=
    model.compile(..., decay=...)  → Keras 3 uses weight_decay=
    from keras.layers.merge import ... → moved to keras.layers

This module is imported by the sprint3 experiment BEFORE the legacy code loads.
It patches the relevant Keras APIs in-place so that Project_3 code works
unchanged with the current Keras version.
"""
from __future__ import annotations

import warnings

# Suppress gymnasium deprecation warning (legacy code imports gym, not gymnasium).
warnings.filterwarnings("ignore", message="Gym has been unmaintained")


def _patch_keras() -> None:
    try:
        import keras
        from keras.optimizers import Adam as _Adam
        from keras.optimizers import schedules
        from keras.src.optimizers.adam import Adam as _AdamK3
    except ImportError:
        return  # nothing to patch

    # Check if already patched.
    if getattr(_AdamK3, "_legacy_patched", False):
        return

    _original_init = _AdamK3.__init__

    def _patched_init(self, learning_rate=0.001, **kwargs):
        # Translate Keras 2-style keyword arguments.
        if "lr" in kwargs:
            lr_val = kwargs.pop("lr")
            if learning_rate == 0.001 and lr_val != 0.001:
                learning_rate = lr_val
        # 'decay' → 'weight_decay'
        if "decay" in kwargs:
            wd = kwargs.pop("decay")
            if wd and "weight_decay" not in kwargs:
                kwargs["weight_decay"] = wd
        _original_init(self, learning_rate=learning_rate, **kwargs)

    _patched_init.__signature__ = None  # type: ignore[attr-defined]
    _AdamK3.__init__ = _patched_init
    _AdamK3._legacy_patched = True  # type: ignore[attr-defined]

    _Adam.__init__ = _patched_init
    _Adam._legacy_patched = True  # type: ignore[attr-defined]

    # K.set_session was removed in Keras 3. Stub it as a no-op.
    try:
        import keras.backend as K
        if not hasattr(K, "set_session"):
            def _set_session_noop(session: object) -> None:
                pass
            K.set_session = _set_session_noop  # type: ignore[assignment]
    except ImportError:
        pass


def _patch_keras_layers() -> None:
    """keras.layers.merge was removed; Add/Concatenate are now in keras.layers."""
    try:
        import keras.layers
        if not hasattr(keras.layers, "merge"):
            import keras.layers._merge as _merge
            keras.layers.merge = _merge  # type: ignore[attr-defined]
    except (ImportError, AttributeError):
        pass


# Run patches immediately on import.
_patch_keras()
_patch_keras_layers()