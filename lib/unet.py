import chainer
import chainer.functions as F
import chainer.links as L

from lib import spec_utils


class Conv2DBNActiv(chainer.Chain):

    def __init__(self, in_channels, out_channels, ksize, stride=1, pad=0,
                 dropout=False, activ=F.relu):
        super(Conv2DBNActiv, self).__init__()
        with self.init_scope():
            self.conv = L.Convolution2D(
                in_channels, out_channels, ksize, stride, pad, nobias=True)
            self.bn = L.BatchNormalization(out_channels)

        self.dropout = dropout
        self.activ = activ

    def __call__(self, x):
        h = self.bn(self.conv(x))

        if self.dropout:
            h = F.dropout(h)

        if self.activ is not None:
            h = self.activ(h)

        return h


class ConvBlock(chainer.Chain):

    def __init__(self, in_channels, out_channels, ksize, stride=1, pad=0,
                 activ=F.leaky_relu, r=16, scse=False):
        super(ConvBlock, self).__init__()
        with self.init_scope():
            self.conv1 = Conv2DBNActiv(
                in_channels, out_channels, ksize, 1, pad, activ=activ)
            self.conv2 = Conv2DBNActiv(
                out_channels, out_channels, ksize, stride, pad, activ=activ)

            if scse:
                self.conv_sc = L.Convolution2D(None, 1, 1)
                self.fc1 = L.Linear(out_channels, out_channels // r)
                self.fc2 = L.Linear(out_channels // r, out_channels)

        self.scse = scse

    def __call__(self, x):
        h1 = self.conv1(x)
        h2 = self.conv2(h1)

        if self.scse:
            sc = F.sigmoid(self.conv_sc(h2))
            se = F.relu(self.fc1(F.average(h2, axis=(2, 3))))
            se = F.sigmoid(self.fc2(se))[:, :, None, None]
            se = F.broadcast_to(se, h2.shape)
            h2 = h2 * sc + h2 * se

        return h2, h1


class BaseUNet(chainer.Chain):

    def __init__(self, ch, pad):
        super(BaseUNet, self).__init__()
        with self.init_scope():
            self.enc1 = ConvBlock(None, ch, 3, stride=2, pad=pad)
            self.enc2 = ConvBlock(None, ch * 2, 3, stride=2, pad=pad)
            self.enc3 = ConvBlock(None, ch * 4, 3, stride=2, pad=pad)
            self.enc4 = ConvBlock(None, ch * 8, 3, stride=2, pad=pad)
            self.enc5 = ConvBlock(None, ch * 16, 3, stride=2, pad=pad)
            self.enc6 = ConvBlock(None, ch * 32, 3, stride=2, pad=pad)

            self.dec6 = Conv2DBNActiv(None, ch * 32, 3, pad=pad, dropout=True)
            self.dec5 = Conv2DBNActiv(None, ch * 16, 3, pad=pad, dropout=True)
            self.dec4 = Conv2DBNActiv(None, ch * 8, 3, pad=pad, dropout=True)
            self.dec3 = Conv2DBNActiv(None, ch * 4, 3, pad=pad)
            self.dec2 = Conv2DBNActiv(None, ch * 2, 3, pad=pad)
            self.dec1 = Conv2DBNActiv(None, ch, 3, pad=pad)

    def __call__(self, x):
        h, e1 = self.enc1(x)
        h, e2 = self.enc2(h)
        h, e3 = self.enc3(h)
        h, e4 = self.enc4(h)
        h, e5 = self.enc5(h)
        h, e6 = self.enc6(h)

        h = F.resize_images(h, (h.shape[2] * 2, h.shape[3] * 2))
        h = self.dec6(spec_utils.crop_and_concat(h, e6))
        h = F.resize_images(h, (h.shape[2] * 2, h.shape[3] * 2))
        h = self.dec5(spec_utils.crop_and_concat(h, e5))
        h = F.resize_images(h, (h.shape[2] * 2, h.shape[3] * 2))
        h = self.dec4(spec_utils.crop_and_concat(h, e4))
        h = F.resize_images(h, (h.shape[2] * 2, h.shape[3] * 2))
        h = self.dec3(spec_utils.crop_and_concat(h, e3))
        h = F.resize_images(h, (h.shape[2] * 2, h.shape[3] * 2))
        h = self.dec2(spec_utils.crop_and_concat(h, e2))
        h = F.resize_images(h, (h.shape[2] * 2, h.shape[3] * 2))
        h = self.dec1(spec_utils.crop_and_concat(h, e1))

        return h


class MultiBandUNet(chainer.Chain):

    def __init__(self):
        super(MultiBandUNet, self).__init__()
        with self.init_scope():
            self.l_band_unet = BaseUNet(16, pad=(1, 0))
            self.h_band_unet = BaseUNet(16, pad=(1, 0))
            self.full_band_unet = BaseUNet(8, pad=(1, 0))

            self.conv = Conv2DBNActiv(None, 16, 3, pad=(1, 0))
            self.out = L.Convolution2D(None, 2, 1, nobias=True)

        self.offset = 160

    def __call__(self, x):
        bandw = x.shape[2] // 2
        diff = (x[:, 0] - x[:, 1])[:, None]
        x_l, x_h = x[:, :, :bandw], x[:, :, bandw:]
        h1 = self.l_band_unet(x_l)
        h2 = self.h_band_unet(x_h)
        h = self.full_band_unet(self.xp.concatenate([x, diff], axis=1))

        h = self.conv(F.concat([h, F.concat([h1, h2], axis=2)]))
        h = F.sigmoid(self.out(h))

        return h
