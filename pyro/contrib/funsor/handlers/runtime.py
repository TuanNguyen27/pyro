# Copyright Contributors to the Pyro project.
# SPDX-License-Identifier: Apache-2.0

from collections import OrderedDict, namedtuple
from enum import Enum


# name_to_dim : dict, dim_to_name : dict, parents : tuple, iter_parents : tuple
class StackFrame(namedtuple('StackFrame', [
            'name_to_dim',
            'dim_to_name',
            'parents',
            'iter_parents',
            'keep',
        ])):

    def read(self, name, dim):
        found_name = self.dim_to_name.get(dim, name)
        found_dim = self.name_to_dim.get(name, dim)
        found = name in self.name_to_dim or dim in self.dim_to_name
        return found_name, found_dim, found

    def write(self, name, dim):
        assert name is not None and dim is not None
        self.dim_to_name[dim] = name
        self.name_to_dim[name] = dim

    def free(self, name, dim):
        self.dim_to_name.pop(dim, None)
        self.name_to_dim.pop(name, None)
        return name, dim


class DimType(Enum):
    """Enumerates the possible types of dimensions to allocate"""
    LOCAL = 0
    GLOBAL = 1
    VISIBLE = 2


DimRequest = namedtuple('DimRequest', ['dim', 'dim_type'])
DimRequest.__new__.__defaults__ = (None, DimType.LOCAL)
NameRequest = namedtuple('NameRequest', ['name', 'dim_type'])
NameRequest.__new__.__defaults__ = (None, DimType.LOCAL)


class DimStack:
    """
    Single piece of global state to keep track of the mapping between names and dimensions.

    Replaces the plate DimAllocator, the enum EnumAllocator, the stack in MarkovMessenger,
    _param_dims and _value_dims in EnumMessenger, and dim_to_symbol in msg['infer']
    """
    def __init__(self):
        self._stack = [StackFrame(
            name_to_dim=OrderedDict(), dim_to_name=OrderedDict(),
            parents=(), iter_parents=(), keep=False,
        )]
        self._first_available_dim = -1
        self.outermost = None

    MAX_DIM = -25

    def set_first_available_dim(self, dim):
        assert dim is None or (self.MAX_DIM < dim < 0)
        old_dim, self._first_available_dim = self._first_available_dim, dim
        return old_dim

    def push(self, frame):
        self._stack.append(frame)

    def pop(self):
        assert len(self._stack) > 1, "cannot pop the global frame"
        return self._stack.pop()

    @property
    def current_frame(self):
        return self._stack[-1]

    @property
    def global_frame(self):
        return self._stack[0]

    @property
    def current_env(self):
        return (self.global_frame, self.current_frame) + self.current_frame.iter_parents + self.current_frame.parents

    def _gendim(self, name_request, dim_request):
        assert isinstance(name_request, NameRequest) and isinstance(dim_request, DimRequest)
        dim_type = dim_request.dim_type

        if name_request.name is None:
            fresh_name = "_pyro_dim_{}".format(-dim_request.dim)
        else:
            fresh_name = name_request.name

        conflict_frames = self.current_env
        if dim_request.dim is None:
            fresh_dim = self._first_available_dim if dim_type != DimType.VISIBLE else -1
            fresh_dim = -1 if fresh_dim is None else fresh_dim
            while any(fresh_dim in p.dim_to_name for p in conflict_frames):
                fresh_dim -= 1
        else:
            fresh_dim = dim_request.dim

        if fresh_dim < self.MAX_DIM or \
                any(fresh_dim in p.dim_to_name for p in conflict_frames) or \
                (dim_type == DimType.VISIBLE and fresh_dim <= self._first_available_dim):
            raise ValueError("Ran out of free dims during allocation for {}".format(fresh_name))

        return fresh_name, fresh_dim

    def request(self, name, dim):
        assert isinstance(name, NameRequest) ^ isinstance(dim, DimRequest)
        if isinstance(dim, DimRequest):
            dim, dim_type = dim.dim, dim.dim_type
        elif isinstance(name, NameRequest):
            name, dim_type = name.name, name.dim_type

        # read dimension
        for frame in self.current_env:
            name, dim, found = frame.read(name, dim)
            if found:
                break

        # generate fresh name or dimension
        if not found:
            name, dim = self._gendim(NameRequest(name, dim_type), DimRequest(dim, dim_type))

            write_frames = (self.global_frame,) if dim_type != DimType.LOCAL else \
                (self.current_frame,) + (self.current_frame.parents if self.current_frame.keep else ())

            # store the fresh dimension
            for frame in write_frames:
                frame.write(name, dim)

        return name, dim


_DIM_STACK = DimStack()  # only one global instance
