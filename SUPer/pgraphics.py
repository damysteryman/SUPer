#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2023 cibo
# This file is part of SUPer <https://github.com/cubicibo/SUPer>.
#
# SUPer is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# SUPer is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with SUPer.  If not, see <http://www.gnu.org/licenses/>.

from numpy import typing as npt
import numpy as np
from typing import Union, Optional
from enum import Enum

from .segments import ODS

class PGraphics:
    @classmethod
    def bitmap_to_ods(cls, bitmap: npt.NDArray[np.uint8], o_id: int, **kwargs) -> list[ODS]:
        assert bitmap.dtype == np.uint8
        height, width = bitmap.shape
        o_vn = kwargs.pop('o_vn', 0)
        data = cls.encode_rle(bitmap)

        return ODS.from_scratch(o_id, o_vn, width, height, data, **kwargs)

    @staticmethod
    def encode_rle(bitmap: npt.NDArray[np.uint8]) -> bytes:
        """
        Encode a 2D map using the RLE defined in 'US 7912305 B1' patent.
        :param bitmap:    Palette mapped image to encode (2d array)
        :return:          Encoded data (vector)
        """
        rle_data = bytearray()

        _bitmap = np.squeeze(bitmap)
        _fp = np.ravel(_bitmap)
        i = 0
        insert_line_end = False

        while i < _fp.size:
            for k in range(1, 16384):
                if (i % _bitmap.shape[1]) + k >= _bitmap.shape[1]:
                    insert_line_end = True
                    break

                if _fp[i+k] != _fp[i]:
                    break

            if _fp[i] != 0: #color
                if k < 3:
                    rle_data += bytearray([_fp[i]]*k)
                elif k <= 63:
                    rle_data += bytearray([0, 0x80 | k, _fp[i]])
                else:
                    rle_data += bytearray([0, 0xC0 | (k >> 8), k&0xFF, _fp[i]])
            else: #transparent
                if k <= 63:
                    rle_data += bytearray([0, k])
                else:
                    rle_data += bytearray([0, 0x40 | (k >> 8), k&0xFF])

            if insert_line_end:
                rle_data += bytearray([0, 0])
                insert_line_end = False
            i += k
        return bytes(rle_data)

    @staticmethod
    def decode_rle(rle_data: Union[bytes, bytearray, ODS, list[ODS]], o_id: Optional[int] = None) -> npt.NDArray[np.uint8]:
        """
        Decode a RLE object, as defined in 'US 7912305 B1' patent.
        :param rle_data:  Data to decode
        :param o_id:      Optional object ID to display, if rle_data is packed ODSes from a DS
        :return:          2D map to associate with the proper palette
        """
        class RLEDecoderState(Enum):
            NEED_MORE = -2
            NEW_CODE  = -1
            SMALL_TSP = 0
            LARGE_TSP = 1
            SMALL_CCO = 2
            LARGE_CCO = 3

        if isinstance(rle_data, ODS):
            rle_data = [rle_data]

        if isinstance(rle_data, list):
            if o_id is not None:
                rle_data = b''.join(map(lambda x: x.data, filter(lambda x: o_id == x.o_id, rle_data)))
            else:
                rle_data = b''.join(map(lambda x: x.data, rle_data))

        plane2d, line_l = [], []
        decoder_state = RLEDecoderState.NEW_CODE
        tmp = 0

        # Always use a state machine, even in place where you totally don't need it.
        for byte in rle_data:
            if decoder_state == RLEDecoderState.NEW_CODE:
                if byte > 0:
                    line_l.append(byte)
                else:
                    decoder_state = RLEDecoderState.NEED_MORE

            elif decoder_state == RLEDecoderState.NEED_MORE:
                if byte == 0:
                    plane2d.append(line_l)
                    line_l = []
                    decoder_state = RLEDecoderState.NEW_CODE
                else:
                    decoder_state = RLEDecoderState(byte >> 6)
                    tmp = byte & 0x3F

                    if decoder_state == RLEDecoderState.SMALL_TSP:
                        line_l.extend([0] * tmp)
                        decoder_state = RLEDecoderState.NEW_CODE

            elif decoder_state == RLEDecoderState.LARGE_TSP:
                tmp = (tmp << 8) + byte
                line_l.extend([0]*tmp)
                decoder_state = RLEDecoderState.NEW_CODE

            elif decoder_state == RLEDecoderState.SMALL_CCO:
                line_l.extend([byte]*tmp)
                decoder_state = RLEDecoderState.NEW_CODE

            elif decoder_state == RLEDecoderState.LARGE_CCO:
                #first pass (some RLE encoders use long code for small distances
                # hence we must check for equal zero...)
                if tmp >= 0:
                    tmp = ((tmp << 8) + byte)*-1
                else: #second pass
                    line_l.extend([byte]*(-1*tmp))
                    decoder_state = RLEDecoderState.NEW_CODE
        return np.asarray(plane2d)

    @staticmethod
    def show(l_ods: list[ODS], palette: Optional[npt.NDArray[np.uint8]] = None) -> None:
        """
        Show the ODS with or without a provided palette. If no palette are provided,
        one is generated that illustrates the encoded animation in the bitmap.
        """
        bitmap = __class__.decode_rle(l_ods)

        # Create a evenly distributed palette using YUV wiht constant luma.
        if palette is None:
            mpe, Mpe = np.min(bitmap), np.max(bitmap)
            n_cols = (Mpe-mpe+1)
            luma = 0.5
            palette = np.zeros((Mpe+1, 3), float)
            angles = np.random.permutation(np.arange(0, (Mpe-mpe)/n_cols, 1/n_cols))

            for angle, k in zip(angles, range(mpe+1, Mpe)):
                angle *= 2*np.pi
                palette[k, 0] = luma + np.cos(angle)/0.88
                palette[k, 1] = luma - np.sin(angle)*0.38 - np.cos(angle)*0.58
                palette[k, 2] = luma + np.sin(angle)/0.49
            palette -= np.min(palette)
            palette /= (np.max(palette)/255)
            palette = np.uint8(np.round(palette))

        try:
            from matplotlib import pyplot as plt
            plt.imshow(palette[bitmap])
        except ModuleNotFoundError:
            from PIL import Image
            Image.fromarray(palette[bitmap], 'RGB').show()
####
